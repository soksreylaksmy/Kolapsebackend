import asyncio
import json
from datetime import datetime, timezone

import httpx
from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.entities import (
    Alert,
    AlertStatus,
    Elder,
    NotificationChannel,
    ChannelType,
)
from app.services.notifications import send_telegram
from app.services.websocket_manager import manager


# =========================================================
# TELEGRAM API HELPERS
# =========================================================

async def answer_callback_query(
    callback_query_id: str,
    text: str,
):
    """
    Tell Telegram that an inline button click was received.
    """

    if not settings.telegram_bot_token:
        return

    url = (
        "https://api.telegram.org/"
        f"bot{settings.telegram_bot_token}/answerCallbackQuery"
    )

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                url,
                json={
                    "callback_query_id": callback_query_id,
                    "text": text,
                },
            )

            response.raise_for_status()

    except httpx.HTTPError as exc:
        print(
            f"Telegram callback response failed: {exc}"
        )


# =========================================================
# TELEGRAM /START CONNECTION
# =========================================================

async def process_telegram_start(
    text: str,
    chat_id: str,
    username: str | None,
):
    if not text.startswith("/start"):
        return

    parts = text.split(maxsplit=1)

    if len(parts) != 2:
        return

    connect_token = parts[1].strip()

    db = SessionLocal()

    try:
        channels = db.scalars(
            select(NotificationChannel).where(
                NotificationChannel.type
                == ChannelType.telegram
            )
        ).all()

        for channel in channels:

            try:
                config = json.loads(
                    channel.config or "{}"
                )

            except json.JSONDecodeError:
                continue

            if (
                config.get("connect_token")
                != connect_token
            ):
                continue

            # Connect this Telegram account
            # to the caregiver.
            channel.config = json.dumps(
                {
                    "chat_id": str(chat_id),
                    "username": username,
                    "connected": True,
                }
            )

            channel.is_active = True

            db.commit()
            db.refresh(channel)

            await send_telegram(
                "KOLAPSE connected successfully!\n\n"
                "You will now receive fall alerts here.",
                str(chat_id),
            )

            print(
                "Telegram connected for "
                f"user_id={channel.user_id}"
            )

            return

    finally:
        db.close()


# =========================================================
# I'M RESPONDING CALLBACK
# =========================================================

async def process_responding_callback(
    callback_query_id: str,
    callback_data: str,
    chat_id: str,
):
    """
    Handle:
        responding:<alert_id>

    Example:
        responding:42
    """

    # -----------------------------------------------------
    # 1. Validate callback data
    # -----------------------------------------------------

    if not callback_data.startswith(
        "responding:"
    ):
        return

    try:
        alert_id = int(
            callback_data.split(":", 1)[1]
        )

    except (ValueError, IndexError):

        await answer_callback_query(
            callback_query_id,
            "Invalid alert.",
        )

        return

    db = SessionLocal()

    try:

        # -------------------------------------------------
        # 2. Find caregiver from Telegram chat
        # -------------------------------------------------

        channels = db.scalars(
            select(NotificationChannel).where(
                NotificationChannel.type
                == ChannelType.telegram
            )
        ).all()

        caregiver_id = None

        for channel in channels:

            try:
                config = json.loads(
                    channel.config or "{}"
                )

            except json.JSONDecodeError:
                continue

            if (
                str(config.get("chat_id"))
                == str(chat_id)
                and config.get("connected") is True
            ):
                caregiver_id = channel.user_id
                break

        if caregiver_id is None:

            await answer_callback_query(
                callback_query_id,
                "Telegram account is not connected.",
            )

            print(
                "Telegram callback rejected: "
                "no connected caregiver."
            )

            return

        # -------------------------------------------------
        # 3. Find alert AND verify ownership
        # -------------------------------------------------

        alert = db.scalar(
            select(Alert)
            .join(
                Elder,
                Alert.elder_id == Elder.id,
            )
            .where(
                Alert.id == alert_id,
                Elder.caregiver_id
                == caregiver_id,
            )
        )

        if not alert:

            await answer_callback_query(
                callback_query_id,
                "Alert not found.",
            )

            print(
                "Telegram callback rejected: "
                f"alert {alert_id} not owned by "
                f"caregiver {caregiver_id}."
            )

            return

        # -------------------------------------------------
        # 4. Check if already resolved
        # -------------------------------------------------

        if alert.status == AlertStatus.resolved:

            await answer_callback_query(
                callback_query_id,
                "This alert is already resolved.",
            )

            return

        # -------------------------------------------------
        # 5. Resolve alert
        # -------------------------------------------------

        now = datetime.now(
            timezone.utc
        )

        alert.status = AlertStatus.resolved

        alert.resolved_at = now

        alert.response_time = max(
            0.0,
            (
                now - alert.timestamp
            ).total_seconds() / 60.0,
        )

        alert.notes = (
            "Caregiver responded through Telegram."
        )

        db.commit()
        db.refresh(alert)

        print(
            "Telegram caregiver responding: "
            f"alert_id={alert.id}"
        )

        # -------------------------------------------------
        # 6. Confirm button click in Telegram
        # -------------------------------------------------

        await answer_callback_query(
            callback_query_id,
            "Response confirmed!",
        )

        # -------------------------------------------------
        # 7. Send confirmation message
        # -------------------------------------------------

        await send_telegram(
            "RESPONSE CONFIRMED\n\n"
            "Thank you. You are now responding "
            "to this fall alert.",
            str(chat_id),
        )

        # -------------------------------------------------
        # 8. Tell frontend LIVE
        # -------------------------------------------------

        await manager.send_user(
            caregiver_id,
            {
                "type": "alert_resolved",
                "alert_id": alert.id,
                "elder_id": alert.elder_id,
                "status": "resolved",
                "resolved_at": (
                    alert.resolved_at.isoformat()
                    if alert.resolved_at
                    else None
                ),
                "response_time": (
                    alert.response_time
                ),
            },
        )

    except Exception as exc:

        db.rollback()

        print(
            "Telegram responding callback "
            f"failed: {exc}"
        )

        await answer_callback_query(
            callback_query_id,
            "Unable to update the alert.",
        )

    finally:
        db.close()


# =========================================================
# MOCK AMBULANCE 119 CALLBACK
# =========================================================

async def process_ambulance_demo_callback(
    callback_query_id: str,
    callback_data: str,
    chat_id: str,
):
    """
    Handle:
        ambulance_demo:<alert_id>

    This is DEMO ONLY.

    It does NOT:
    - call 119
    - contact emergency services
    - resolve the fall alert
    """

    # -----------------------------------------------------
    # 1. Validate callback
    # -----------------------------------------------------

    if not callback_data.startswith(
        "ambulance_demo:"
    ):
        return

    try:
        alert_id = int(
            callback_data.split(":", 1)[1]
        )

    except (ValueError, IndexError):

        await answer_callback_query(
            callback_query_id,
            "Invalid ambulance request.",
        )

        return

    # -----------------------------------------------------
    # 2. Verify caregiver and alert ownership
    # -----------------------------------------------------

    db = SessionLocal()

    try:
        channels = db.scalars(
            select(NotificationChannel).where(
                NotificationChannel.type
                == ChannelType.telegram
            )
        ).all()

        caregiver_id = None

        for channel in channels:

            try:
                config = json.loads(
                    channel.config or "{}"
                )

            except json.JSONDecodeError:
                continue

            if (
                str(config.get("chat_id"))
                == str(chat_id)
                and config.get("connected") is True
            ):
                caregiver_id = channel.user_id
                break

        if caregiver_id is None:

            await answer_callback_query(
                callback_query_id,
                "Telegram account is not connected.",
            )

            return

        alert = db.scalar(
            select(Alert)
            .join(
                Elder,
                Alert.elder_id == Elder.id,
            )
            .where(
                Alert.id == alert_id,
                Elder.caregiver_id
                == caregiver_id,
            )
        )

        if not alert:

            await answer_callback_query(
                callback_query_id,
                "Alert not found.",
            )

            return

        # -------------------------------------------------
        # 3. Confirm button click
        # -------------------------------------------------

        await answer_callback_query(
            callback_query_id,
            "Ambulance 119 demo activated.",
        )

        # -------------------------------------------------
        # 4. Send DEMO message
        # -------------------------------------------------

        await send_telegram(
            "AMBULANCE 119\n\n"
            "Connecting to emergency ambulance services...\n\n"
            "DEMO MODE\n"
            "No real emergency call was placed.\n\n"
            f"Fall Alert ID: {alert.id}",
            str(chat_id),
        )

        print(
            "Telegram Ambulance 119 demo: "
            f"alert_id={alert.id}"
        )

    except Exception as exc:

        print(
            "Telegram ambulance demo callback "
            f"failed: {exc}"
        )

        await answer_callback_query(
            callback_query_id,
            "Unable to start ambulance demo.",
        )

    finally:
        db.close()


# =========================================================
# TELEGRAM POLLING LOOP
# =========================================================

async def telegram_polling_loop():

    if not settings.telegram_bot_token:

        print(
            "Telegram polling disabled: "
            "no bot token configured."
        )

        return

    url = (
        "https://api.telegram.org/"
        f"bot{settings.telegram_bot_token}/getUpdates"
    )

    offset = 0

    print(
        "Telegram polling started"
    )

    async with httpx.AsyncClient(
        timeout=35
    ) as client:

        while True:

            try:
                response = await client.get(
                    url,
                    params={
                        "timeout": 30,
                        "offset": offset,
                    },
                )

                response.raise_for_status()

                data = response.json()

                for update in data.get(
                    "result",
                    [],
                ):

                    offset = (
                        update["update_id"] + 1
                    )

                    # =====================================
                    # NORMAL TELEGRAM MESSAGE
                    # =====================================

                    message = update.get(
                        "message"
                    )

                    if message:

                        text = message.get(
                            "text",
                            "",
                        )

                        chat = message.get(
                            "chat",
                            {},
                        )

                        sender = message.get(
                            "from",
                            {},
                        )

                        chat_id = str(
                            chat.get("id")
                        )

                        username = sender.get(
                            "username"
                        )

                        await process_telegram_start(
                            text=text,
                            chat_id=chat_id,
                            username=username,
                        )

                        continue

                    # =====================================
                    # INLINE BUTTON CALLBACK
                    # =====================================

                    callback_query = update.get(
                        "callback_query"
                    )

                    if callback_query:

                        callback_query_id = str(
                            callback_query.get(
                                "id"
                            )
                        )

                        callback_data = (
                            callback_query.get(
                                "data",
                                "",
                            )
                        )

                        callback_message = (
                            callback_query.get(
                                "message",
                                {},
                            )
                        )

                        callback_chat = (
                            callback_message.get(
                                "chat",
                                {},
                            )
                        )

                        chat_id = str(
                            callback_chat.get(
                                "id"
                            )
                        )

                        # ---------------------------------
                        # I'M RESPONDING
                        # ---------------------------------

                        if callback_data.startswith(
                            "responding:"
                        ):

                            await process_responding_callback(
                                callback_query_id=(
                                    callback_query_id
                                ),
                                callback_data=(
                                    callback_data
                                ),
                                chat_id=chat_id,
                            )

                            continue

                        # ---------------------------------
                        # MOCK CALL AMBULANCE 119
                        # ---------------------------------

                        if callback_data.startswith(
                            "ambulance_demo:"
                        ):

                            await process_ambulance_demo_callback(
                                callback_query_id=(
                                    callback_query_id
                                ),
                                callback_data=(
                                    callback_data
                                ),
                                chat_id=chat_id,
                            )

                            continue

                        # ---------------------------------
                        # UNKNOWN BUTTON
                        # ---------------------------------

                        await answer_callback_query(
                            callback_query_id,
                            "Unknown action.",
                        )

            except asyncio.CancelledError:

                print(
                    "Telegram polling stopped"
                )

                raise

            except Exception as exc:

                print(
                    f"Telegram polling error: {exc}"
                )

                await asyncio.sleep(5)