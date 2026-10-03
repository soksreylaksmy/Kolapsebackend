import asyncio
import json
from datetime import datetime, time, timezone

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import (
    get_current_user,
    require_ai_key,
)
from app.db.session import (
    get_db,
    SessionLocal,
)
from app.models.entities import (
    ActivityLog,
    Elder,
    User,
    Camera,
    NotificationChannel,
    ChannelType,
)
from app.schemas.common import (
    ActivityCreate,
    ActivityOut,
)
from app.services.activity_service import record_activity
from app.services.notifications import send_telegram
from app.services.websocket_manager import manager


router = APIRouter(
    prefix="/activity",
    tags=["Activity"],
)


# =========================================================
# TELEGRAM SEND + SUCCESS COUNTER
# =========================================================

async def send_telegram_and_count(
    message: str,
    chat_id: str,
    channel_id: int,
    caregiver_id: int,
    reply_markup: dict | None = None,
):
    sent = await send_telegram(
        message,
        chat_id,
        reply_markup=reply_markup,
    )

    if not sent:
        print("Telegram notification was not sent.")
        return

    # Separate DB session because this runs
    # as a background task.
    db = SessionLocal()

    try:
        channel = db.get(
            NotificationChannel,
            channel_id,
        )

        if not channel:
            print(
                f"Notification channel "
                f"{channel_id} not found."
            )
            return

        # Increase Total Sent
        channel.total_sent = (
            channel.total_sent or 0
        ) + 1

        db.commit()
        db.refresh(channel)

        print(
            "Telegram notification sent successfully. "
            f"Total sent: {channel.total_sent}"
        )

        # Tell frontend notification data changed
        await manager.send_user(
            caregiver_id,
            {
                "type": "notification_sent",
                "channel": "telegram",
                "channel_id": channel.id,
                "total_sent": channel.total_sent,
            },
        )

    except Exception as exc:
        db.rollback()

        print(
            "Failed to update Telegram "
            f"notification counter: {exc}"
        )

    finally:
        db.close()


# =========================================================
# AI ACTIVITY INGESTION
# =========================================================

@router.post(
    "/log",
    response_model=ActivityOut,
    status_code=201,
)
async def ingest_activity(
    payload: ActivityCreate,
    x_ai_key: str | None = Header(default=None),
    x_device_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    # -----------------------------------------------------
    # 1. Verify KOLAPSE AI service
    # -----------------------------------------------------

    require_ai_key(x_ai_key)

    # -----------------------------------------------------
    # 2. Require registered camera device key
    # -----------------------------------------------------

    if not x_device_key:
        raise HTTPException(
            status_code=401,
            detail="Missing camera device key",
        )

    # -----------------------------------------------------
    # 3. Find active registered camera
    # -----------------------------------------------------

    camera = db.scalar(
        select(Camera).where(
            Camera.device_key == x_device_key,
            Camera.is_active.is_(True),
        )
    )

    if not camera:
        raise HTTPException(
            status_code=401,
            detail="Invalid or inactive camera device",
        )

    # -----------------------------------------------------
    # 4. Camera determines elder and location
    #
    # We do NOT trust elder_id or location sent
    # by the AI runner.
    # -----------------------------------------------------

    secure_payload = ActivityCreate(
        elder_id=camera.elder_id,
        activity=payload.activity,
        confidence=payload.confidence,
        location=camera.location,
        source=payload.source,
    )

    # -----------------------------------------------------
    # 5. Record activity
    # -----------------------------------------------------

    try:
        log, alert, elder = record_activity(
            db,
            secure_payload,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        )

    # =====================================================
    # FALL ALERT
    # =====================================================

    if alert:

        # -------------------------------------------------
        # 1. Send real-time WebSocket event
        # -------------------------------------------------

        event = {
            "type": "fall_alert",
            "alert_id": alert.id,
            "elder_id": elder.id,
            "elder_name": elder.name,
            "activity": log.activity.value,
            "confidence": log.confidence,
            "location": log.location,
            "timestamp": alert.timestamp.isoformat(),
        }

        await manager.send_user(
            elder.caregiver_id,
            event,
        )

        # -------------------------------------------------
        # 2. Find THIS caregiver's active Telegram
        # -------------------------------------------------

        telegram_channel = db.scalar(
            select(NotificationChannel).where(
                NotificationChannel.user_id
                == elder.caregiver_id,

                NotificationChannel.type
                == ChannelType.telegram,

                NotificationChannel.is_active.is_(True),
            )
        )

        # -------------------------------------------------
        # 3. Send Telegram fall alert
        # -------------------------------------------------

        if telegram_channel:

            try:
                telegram_config = json.loads(
                    telegram_channel.config or "{}"
                )

                telegram_chat_id = telegram_config.get(
                    "chat_id"
                )

                connected = telegram_config.get(
                    "connected",
                    False,
                )

                if telegram_chat_id and connected:

                    location = (
                        log.location
                        if log.location
                        else "Unknown location"
                    )

                    telegram_message = (
                        "KOLAPSE FALL ALERT\n\n"
                        f"Patient: {elder.name}\n"
                        f"Location: {location}\n"
                        f"Confidence: "
                        f"{log.confidence:.0%}\n"
                        f"Time: "
                        f"{alert.timestamp.strftime('%Y-%m-%d %H:%M:%S')}"
                    )

                    # -------------------------------------
                    # Telegram buttons
                    # -------------------------------------

                    telegram_buttons = {
                        "inline_keyboard": [
                            [
                                {
                                    "text": "I'M RESPONDING",
                                    "callback_data": (
                                        f"responding:{alert.id}"
                                    ),
                                }
                            ],
                            [
                                {
                                    "text": "CALL AMBULANCE 119",
                                    "callback_data": (
                                        f"ambulance_demo:{alert.id}"
                                    ),
                                }
                            ],
                        ]
                    }

                    # -------------------------------------
                    # Send Telegram in background
                    # -------------------------------------

                    asyncio.create_task(
                        send_telegram_and_count(
                            telegram_message,
                            str(telegram_chat_id),
                            telegram_channel.id,
                            elder.caregiver_id,
                            telegram_buttons,
                        )
                    )

            except (
                json.JSONDecodeError,
                TypeError,
            ) as exc:

                print(
                    "Invalid Telegram channel "
                    f"configuration: {exc}"
                )

    return log


# =========================================================
# ELDER OWNERSHIP CHECK
# =========================================================

def ensure_owned(
    elder_id: int,
    current: User,
    db: Session,
):
    elder_exists = db.scalar(
        select(Elder.id).where(
            Elder.id == elder_id,
            Elder.caregiver_id == current.id,
        )
    )

    if not elder_exists:
        raise HTTPException(
            status_code=404,
            detail="Elder not found",
        )


# =========================================================
# CURRENT ACTIVITY
# =========================================================

@router.get(
    "/current/{elder_id}",
    response_model=ActivityOut | None,
)
def current_activity(
    elder_id: int,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ensure_owned(
        elder_id,
        current,
        db,
    )

    return db.scalar(
        select(ActivityLog)
        .where(
            ActivityLog.elder_id == elder_id
        )
        .order_by(
            ActivityLog.timestamp.desc()
        )
        .limit(1)
    )


# =========================================================
# ACTIVITY HISTORY
# =========================================================

@router.get(
    "/history/{elder_id}",
    response_model=list[ActivityOut],
)
def history(
    elder_id: int,
    limit: int = Query(
        100,
        ge=1,
        le=1000,
    ),
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ensure_owned(
        elder_id,
        current,
        db,
    )

    return list(
        db.scalars(
            select(ActivityLog)
            .where(
                ActivityLog.elder_id == elder_id
            )
            .order_by(
                ActivityLog.timestamp.desc()
            )
            .limit(limit)
        )
    )


# =========================================================
# ACTIVITY SUMMARY
# =========================================================

@router.get("/summary/{elder_id}")
def summary(
    elder_id: int,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ensure_owned(
        elder_id,
        current,
        db,
    )

    today = datetime.now(
        timezone.utc
    ).date()

    start = datetime.combine(
        today,
        time.min,
        tzinfo=timezone.utc,
    )

    rows = db.execute(
        select(
            ActivityLog.activity,
            func.count(ActivityLog.id),
        )
        .where(
            ActivityLog.elder_id == elder_id,
            ActivityLog.timestamp >= start,
        )
        .group_by(
            ActivityLog.activity
        )
    ).all()

    latest = db.scalar(
        select(ActivityLog)
        .where(
            ActivityLog.elder_id == elder_id
        )
        .order_by(
            ActivityLog.timestamp.desc()
        )
        .limit(1)
    )

    return {
        "elder_id": elder_id,
        "date": today.isoformat(),
        "counts": {
            activity.value: count
            for activity, count in rows
        },
        "latest": (
            ActivityOut
            .model_validate(latest)
            .model_dump(mode="json")
            if latest
            else None
        ),
    }