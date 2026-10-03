import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ActivityType(str, enum.Enum):
    falling = "falling"
    lying = "lying"
    sitting = "sitting"
    standing = "standing"
    walking = "walking"


class Severity(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"


class AlertStatus(str, enum.Enum):
    unresolved = "unresolved"
    resolved = "resolved"


class ChannelType(str, enum.Enum):
    telegram = "telegram"
    sms = "sms"
    email = "email"
    call = "call"


# =========================================================
# USER / CAREGIVER
# =========================================================

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    name: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
    )

    password_hash: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    auth_provider: Mapped[str] = mapped_column(
        String(30),
        default="local",
        nullable=False,
    )

    google_sub: Mapped[str | None] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=True,
    )

    # -----------------------------------------------------
    # KOLAPSE ACCOUNT MANAGEMENT
    # -----------------------------------------------------

    # "customer" or "admin"
    role: Mapped[str] = mapped_column(
        String(30),
        default="customer",
        nullable=False,
    )

    phone: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    # basic / vip / facility
    plan: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    # pending_setup / active / suspended
    setup_status: Mapped[str] = mapped_column(
        String(30),
        default="pending_setup",
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    elders: Mapped[list["Elder"]] = relationship(
        back_populates="caregiver",
        cascade="all, delete-orphan",
    )

# =========================================================
# ELDER
# =========================================================

class Elder(Base):
    __tablename__ = "elders"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    caregiver_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    name: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )

    age: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    gender: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    room: Mapped[str] = mapped_column(
        String(160),
        nullable=False,
    )

    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    photo: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    caregiver: Mapped["User"] = relationship(
        back_populates="elders",
    )

    activities: Mapped[list["ActivityLog"]] = relationship(
        back_populates="elder",
        cascade="all, delete-orphan",
    )

    alerts: Mapped[list["Alert"]] = relationship(
        back_populates="elder",
        cascade="all, delete-orphan",
    )

    cameras: Mapped[list["Camera"]] = relationship(
        back_populates="elder",
        cascade="all, delete-orphan",
    )


# =========================================================
# CAMERA
# =========================================================

class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    elder_id: Mapped[int] = mapped_column(
        ForeignKey("elders.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    name: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )

    location: Mapped[str] = mapped_column(
        String(160),
        nullable=False,
    )

    device_key: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    elder: Mapped["Elder"] = relationship(
        back_populates="cameras",
    )


# =========================================================
# ACTIVITY LOG
# =========================================================

class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    elder_id: Mapped[int] = mapped_column(
        ForeignKey("elders.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    activity: Mapped[ActivityType] = mapped_column(
        Enum(ActivityType),
        index=True,
        nullable=False,
    )

    confidence: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    location: Mapped[str] = mapped_column(
        String(160),
        nullable=False,
    )

    source: Mapped[str] = mapped_column(
        String(60),
        default="ai",
        nullable=False,
    )

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        index=True,
        nullable=False,
    )

    elder: Mapped["Elder"] = relationship(
        back_populates="activities",
    )


# =========================================================
# ALERT
# =========================================================

class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    elder_id: Mapped[int] = mapped_column(
        ForeignKey("elders.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    activity_log_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "activity_logs.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    severity: Mapped[Severity] = mapped_column(
        Enum(Severity),
        default=Severity.high,
        nullable=False,
    )

    status: Mapped[AlertStatus] = mapped_column(
        Enum(AlertStatus),
        default=AlertStatus.unresolved,
        index=True,
        nullable=False,
    )

    response_time: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        index=True,
        nullable=False,
    )

    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    elder: Mapped["Elder"] = relationship(
        back_populates="alerts",
    )


# =========================================================
# NOTIFICATION CHANNEL
# =========================================================

class NotificationChannel(Base):
    __tablename__ = "notification_channels"

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "type",
            name="uq_notification_user_type",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
        ),
        index=True,
        nullable=False,
    )

    type: Mapped[ChannelType] = mapped_column(
        Enum(ChannelType),
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    config: Mapped[str] = mapped_column(
        Text,
        default="{}",
        nullable=False,
    )

    total_sent: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )