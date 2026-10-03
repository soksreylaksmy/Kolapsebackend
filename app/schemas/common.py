from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.entities import (
    ActivityType,
    AlertStatus,
    ChannelType,
    Severity,
)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Message(BaseModel):
    message: str


# =========================================================
# AUTHENTICATION
# =========================================================

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class GoogleLoginRequest(BaseModel):
    credential: str = Field(min_length=1)


# =========================================================
# USER
# =========================================================

class UserCreate(BaseModel):
    name: str = Field(
        min_length=2,
        max_length=120,
    )

    email: EmailStr

    password: str = Field(
        min_length=8,
        max_length=128,
    )


class UserUpdate(BaseModel):
    name: str | None = Field(
        default=None,
        min_length=2,
        max_length=120,
    )

    email: EmailStr | None = None

    password: str | None = Field(
        default=None,
        min_length=8,
        max_length=128,
    )


class UserOut(ORMModel):
    id: int
    name: str
    email: EmailStr

    role: str
    phone: str | None
    plan: str | None
    setup_status: str

    is_active: bool
    created_at: datetime


# =========================================================
# ELDER
# =========================================================

class ElderCreate(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=120,
    )

    age: int = Field(
        ge=50,
        le=130,
    )

    gender: str | None = Field(
        default=None,
        max_length=30,
    )

    room: str = Field(
        min_length=1,
        max_length=160,
    )

    notes: str | None = None
    photo: str | None = None


class ElderUpdate(BaseModel):
    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=120,
    )

    age: int | None = Field(
        default=None,
        ge=50,
        le=130,
    )

    gender: str | None = Field(
        default=None,
        max_length=30,
    )

    room: str | None = Field(
        default=None,
        min_length=1,
        max_length=160,
    )

    notes: str | None = None
    photo: str | None = None


class ElderOut(ORMModel):
    id: int
    caregiver_id: int
    name: str
    age: int
    gender: str | None
    room: str
    notes: str | None
    photo: str | None
    created_at: datetime


# =========================================================
# ACTIVITY
# =========================================================

class ActivityCreate(BaseModel):
    elder_id: int

    activity: ActivityType

    confidence: float = Field(
        ge=0.0,
        le=1.0,
    )

    location: str = Field(
        min_length=1,
        max_length=160,
    )

    source: str = Field(
        default="ai",
        max_length=60,
    )


class ActivityOut(ORMModel):
    id: int
    elder_id: int
    activity: ActivityType
    confidence: float
    location: str
    source: str
    timestamp: datetime


# =========================================================
# ALERT
# =========================================================

class AlertResolve(BaseModel):
    notes: str | None = None


class AlertOut(ORMModel):
    id: int
    elder_id: int
    activity_log_id: int | None
    severity: Severity
    status: AlertStatus
    response_time: float | None
    notes: str | None
    timestamp: datetime
    resolved_at: datetime | None


# =========================================================
# NOTIFICATION CHANNEL
# =========================================================

class ChannelCreate(BaseModel):
    type: ChannelType
    is_active: bool = False
    config: str = "{}"


class ChannelUpdate(BaseModel):
    is_active: bool | None = None
    config: str | None = None


class ChannelOut(ORMModel):
    id: int
    user_id: int
    type: ChannelType
    is_active: bool
    config: str
    total_sent: int
    created_at: datetime