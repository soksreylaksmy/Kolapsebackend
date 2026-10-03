import json
import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.entities import (
    ChannelType,
    NotificationChannel,
    User,
)
from app.schemas.common import (
    ChannelCreate,
    ChannelOut,
    ChannelUpdate,
)


router = APIRouter(
    prefix="/notifications",
    tags=["Notifications"],
)


# =========================================================
# GET NOTIFICATION CHANNELS
# =========================================================

@router.get(
    "/channels",
    response_model=list[ChannelOut],
)
def channels(
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list(
        db.scalars(
            select(NotificationChannel).where(
                NotificationChannel.user_id == current.id
            )
        )
    )


# =========================================================
# CREATE NOTIFICATION CHANNEL
# =========================================================

@router.post(
    "/channels",
    response_model=ChannelOut,
    status_code=201,
)
def create_channel(
    payload: ChannelCreate,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    exists = db.scalar(
        select(NotificationChannel).where(
            NotificationChannel.user_id == current.id,
            NotificationChannel.type == payload.type,
        )
    )

    if exists:
        raise HTTPException(
            status_code=409,
            detail="Channel already exists",
        )

    channel = NotificationChannel(
        user_id=current.id,
        **payload.model_dump(),
    )

    db.add(channel)
    db.commit()
    db.refresh(channel)

    return channel


# =========================================================
# UPDATE NOTIFICATION CHANNEL
# =========================================================

@router.put(
    "/channels/{channel_id}",
    response_model=ChannelOut,
)
def update_channel(
    channel_id: int,
    payload: ChannelUpdate,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    channel = db.scalar(
        select(NotificationChannel).where(
            NotificationChannel.id == channel_id,
            NotificationChannel.user_id == current.id,
        )
    )

    if not channel:
        raise HTTPException(
            status_code=404,
            detail="Notification channel not found",
        )

    for key, value in payload.model_dump(
        exclude_unset=True
    ).items():
        setattr(channel, key, value)

    db.commit()
    db.refresh(channel)

    return channel


# =========================================================
# SEED DEFAULT CHANNELS
# =========================================================

@router.post(
    "/seed",
    response_model=list[ChannelOut],
)
def seed(
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    existing = set(
        db.scalars(
            select(NotificationChannel.type).where(
                NotificationChannel.user_id == current.id
            )
        ).all()
    )

    for channel_type in ChannelType:
        if channel_type not in existing:
            db.add(
                NotificationChannel(
                    user_id=current.id,
                    type=channel_type,
                    is_active=False,
                    config="{}",
                )
            )

    db.commit()

    return list(
        db.scalars(
            select(NotificationChannel).where(
                NotificationChannel.user_id == current.id
            )
        )
    )


# =========================================================
# CONNECT TELEGRAM
# =========================================================

@router.post("/telegram/connect")
def connect_telegram(
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Find this caregiver's Telegram channel
    channel = db.scalar(
        select(NotificationChannel).where(
            NotificationChannel.user_id == current.id,
            NotificationChannel.type == ChannelType.telegram,
        )
    )

    # Create Telegram channel if it doesn't exist
    if not channel:
        channel = NotificationChannel(
            user_id=current.id,
            type=ChannelType.telegram,
            is_active=False,
            config="{}",
        )

        db.add(channel)
        db.commit()
        db.refresh(channel)

    # Generate a random secure connection token
    connect_token = secrets.token_urlsafe(32)

    # Store token temporarily
    channel.config = json.dumps(
        {
            "connect_token": connect_token,
            "connected": False,
        }
    )

    # Keep Telegram inactive until connection finishes
    channel.is_active = False

    db.commit()
    db.refresh(channel)

    # Link to your Telegram bot
    telegram_url = (
        "https://t.me/kolapseklbot"
        f"?start={connect_token}"
    )

    return {
        "message": "Telegram connection created",
        "telegram_url": telegram_url,
        "connected": False,
    }