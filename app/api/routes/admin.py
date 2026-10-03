import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.security import require_admin
from app.db.session import get_db
from app.models.entities import Camera, Elder, NotificationChannel, User
from app.schemas.common import ElderCreate


router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
    dependencies=[Depends(require_admin)],
)


# =========================================================
# ADMIN REQUEST SCHEMAS
# =========================================================

class AdminCustomerCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=50)
    plan: str | None = Field(default=None, max_length=30)


class AdminCustomerUpdate(BaseModel):
    name: str | None = Field(
        default=None,
        min_length=2,
        max_length=120,
    )
    phone: str | None = Field(
        default=None,
        max_length=50,
    )
    plan: str | None = Field(
        default=None,
        max_length=30,
    )
    setup_status: str | None = Field(
        default=None,
        max_length=30,
    )
    is_active: bool | None = None


class AdminCameraCreate(BaseModel):
    elder_id: int
    name: str = Field(min_length=1, max_length=120)
    location: str = Field(min_length=1, max_length=160)


class AdminCameraUpdate(BaseModel):
    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=120,
    )
    location: str | None = Field(
        default=None,
        min_length=1,
        max_length=160,
    )
    is_active: bool | None = None


# =========================================================
# HELPERS
# =========================================================

VALID_PLANS = {
    "basic",
    "vip",
    "facility",
}

VALID_SETUP_STATUSES = {
    "pending_setup",
    "active",
    "suspended",
}


def validate_plan(plan: str | None) -> str | None:
    if plan is None:
        return None

    normalized = plan.lower().strip()

    if normalized not in VALID_PLANS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Plan must be basic, vip, or facility",
        )

    return normalized


def validate_setup_status(value: str) -> str:
    normalized = value.lower().strip()

    if normalized not in VALID_SETUP_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Setup status must be pending_setup, "
                "active, or suspended"
            ),
        )

    return normalized


def generate_device_key() -> str:
    return secrets.token_urlsafe(32)


def serialize_camera(camera: Camera) -> dict:
    return {
        "id": camera.id,
        "elder_id": camera.elder_id,
        "name": camera.name,
        "location": camera.location,
        "is_active": camera.is_active,
        "created_at": camera.created_at,
    }


def serialize_elder(
    elder: Elder,
    include_cameras: bool = True,
) -> dict:
    data = {
        "id": elder.id,
        "caregiver_id": elder.caregiver_id,
        "name": elder.name,
        "age": elder.age,
        "gender": elder.gender,
        "room": elder.room,
        "notes": elder.notes,
        "photo": elder.photo,
        "created_at": elder.created_at,
    }

    if include_cameras:
        data["cameras"] = [
            serialize_camera(camera)
            for camera in elder.cameras
        ]

    return data


def serialize_customer(
    user: User,
    include_elders: bool = True,
) -> dict:
    data = {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "phone": user.phone,
        "plan": user.plan,
        "role": user.role,
        "setup_status": user.setup_status,
        "auth_provider": user.auth_provider,
        "google_connected": bool(user.google_sub),
        "is_active": user.is_active,
        "created_at": user.created_at,
    }

    if include_elders:
        data["elders"] = [
            serialize_elder(elder)
            for elder in user.elders
        ]

    return data


def get_customer_or_404(
    db: Session,
    customer_id: int,
) -> User:
    customer = db.scalar(
        select(User)
        .options(
            selectinload(User.elders)
            .selectinload(Elder.cameras)
        )
        .where(
            User.id == customer_id,
            User.role == "customer",
        )
    )

    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found",
        )

    return customer


def get_elder_or_404(
    db: Session,
    elder_id: int,
) -> Elder:
    elder = db.scalar(
        select(Elder)
        .options(selectinload(Elder.cameras))
        .where(Elder.id == elder_id)
    )

    if not elder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Elder not found",
        )

    return elder


# =========================================================
# ADMIN OVERVIEW
# =========================================================

@router.get("/overview")
def admin_overview(
    db: Session = Depends(get_db),
):
    customers = db.scalar(
        select(func.count(User.id)).where(
            User.role == "customer"
        )
    ) or 0

    pending_customers = db.scalar(
        select(func.count(User.id)).where(
            User.role == "customer",
            User.setup_status == "pending_setup",
        )
    ) or 0

    active_customers = db.scalar(
        select(func.count(User.id)).where(
            User.role == "customer",
            User.setup_status == "active",
        )
    ) or 0

    elders = db.scalar(
        select(func.count(Elder.id))
    ) or 0

    cameras = db.scalar(
        select(func.count(Camera.id))
    ) or 0

    active_cameras = db.scalar(
        select(func.count(Camera.id)).where(
            Camera.is_active.is_(True)
        )
    ) or 0

    return {
        "customers": customers,
        "pending_customers": pending_customers,
        "active_customers": active_customers,
        "elders": elders,
        "cameras": cameras,
        "active_cameras": active_cameras,
    }


# =========================================================
# CUSTOMERS
# =========================================================

@router.get("/customers")
def list_customers(
    db: Session = Depends(get_db),
):
    customers = db.scalars(
        select(User)
        .options(
            selectinload(User.elders)
            .selectinload(Elder.cameras)
        )
        .where(User.role == "customer")
        .order_by(User.created_at.desc())
    ).unique().all()

    return [
        serialize_customer(customer)
        for customer in customers
    ]


@router.get("/customers/{customer_id}")
def get_customer(
    customer_id: int,
    db: Session = Depends(get_db),
):
    customer = get_customer_or_404(
        db,
        customer_id,
    )

    return serialize_customer(customer)


@router.post(
    "/customers",
    status_code=status.HTTP_201_CREATED,
)
def create_customer(
    payload: AdminCustomerCreate,
    db: Session = Depends(get_db),
):
    email = payload.email.lower().strip()

    existing = db.scalar(
        select(User).where(User.email == email)
    )

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists",
        )

    customer = User(
        name=payload.name.strip(),
        email=email,

        # Customer can connect Google after the
        # KOLAPSE team creates the account.
        password_hash=None,
        auth_provider="google",
        google_sub=None,

        role="customer",
        phone=(
            payload.phone.strip()
            if payload.phone
            else None
        ),
        plan=validate_plan(payload.plan),
        setup_status="pending_setup",
        is_active=True,
    )

    db.add(customer)
    db.commit()
    db.refresh(customer)

    return serialize_customer(
        customer,
        include_elders=False,
    )


@router.patch("/customers/{customer_id}")
def update_customer(
    customer_id: int,
    payload: AdminCustomerUpdate,
    db: Session = Depends(get_db),
):
    customer = get_customer_or_404(
        db,
        customer_id,
    )

    if payload.name is not None:
        customer.name = payload.name.strip()

    if payload.phone is not None:
        customer.phone = (
            payload.phone.strip()
            if payload.phone.strip()
            else None
        )

    if payload.plan is not None:
        customer.plan = validate_plan(payload.plan)

    if payload.setup_status is not None:
        customer.setup_status = validate_setup_status(
            payload.setup_status
        )

    if payload.is_active is not None:
        customer.is_active = payload.is_active

    db.commit()
    db.refresh(customer)

    customer = get_customer_or_404(
        db,
        customer.id,
    )

    return serialize_customer(customer)



@router.delete("/customers/{customer_id}")
def delete_customer(
    customer_id: int,
    db: Session = Depends(get_db),
):
    customer = get_customer_or_404(db, customer_id)

    customer_name = customer.name
    customer_email = customer.email

    channels = db.scalars(
        select(NotificationChannel).where(
            NotificationChannel.user_id == customer.id
        )
    ).all()

    for channel in channels:
        db.delete(channel)

    db.delete(customer)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Customer could not be deleted because related data "
                "is still referenced."
            ),
        )

    return {
        "message": "Customer deleted successfully",
        "customer_id": customer_id,
        "name": customer_name,
        "email": customer_email,
    }


# =========================================================
# ELDERS
# =========================================================

@router.post(
    "/customers/{customer_id}/elders",
    status_code=status.HTTP_201_CREATED,
)
def create_elder_for_customer(
    customer_id: int,
    payload: ElderCreate,
    db: Session = Depends(get_db),
):
    customer = get_customer_or_404(
        db,
        customer_id,
    )

    elder = Elder(
        caregiver_id=customer.id,
        name=payload.name.strip(),
        age=payload.age,
        gender=(
            payload.gender.strip()
            if payload.gender
            else None
        ),
        room=payload.room.strip(),
        notes=payload.notes,
        photo=payload.photo,
    )

    db.add(elder)
    db.commit()
    db.refresh(elder)

    return serialize_elder(
        elder,
        include_cameras=False,
    )


@router.get("/elders/{elder_id}")
def admin_get_elder(
    elder_id: int,
    db: Session = Depends(get_db),
):
    elder = get_elder_or_404(
        db,
        elder_id,
    )

    return serialize_elder(elder)


# =========================================================
# CAMERAS
# =========================================================

@router.post(
    "/cameras",
    status_code=status.HTTP_201_CREATED,
)
def register_camera(
    payload: AdminCameraCreate,
    db: Session = Depends(get_db),
):
    elder = get_elder_or_404(
        db,
        payload.elder_id,
    )

    # Generate a unique device identity.
    # The customer never chooses this value.
    while True:
        device_key = generate_device_key()

        existing = db.scalar(
            select(Camera).where(
                Camera.device_key == device_key
            )
        )

        if not existing:
            break

    camera = Camera(
        elder_id=elder.id,
        name=payload.name.strip(),
        location=payload.location.strip(),
        device_key=device_key,
        is_active=True,
    )

    db.add(camera)
    db.commit()
    db.refresh(camera)

    return {
        "camera": serialize_camera(camera),

        # Device key is returned only when provisioning.
        # Do not display this on the normal customer dashboard.
        "device_key": device_key,
    }


@router.patch("/cameras/{camera_id}")
def update_camera(
    camera_id: int,
    payload: AdminCameraUpdate,
    db: Session = Depends(get_db),
):
    camera = db.get(Camera, camera_id)

    if not camera:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Camera not found",
        )

    if payload.name is not None:
        camera.name = payload.name.strip()

    if payload.location is not None:
        camera.location = payload.location.strip()

    if payload.is_active is not None:
        camera.is_active = payload.is_active

    db.commit()
    db.refresh(camera)

    return serialize_camera(camera)


@router.post("/cameras/{camera_id}/rotate-device-key")
def rotate_camera_device_key(
    camera_id: int,
    db: Session = Depends(get_db),
):
    camera = db.get(Camera, camera_id)

    if not camera:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Camera not found",
        )

    while True:
        device_key = generate_device_key()

        existing = db.scalar(
            select(Camera).where(
                Camera.device_key == device_key
            )
        )

        if not existing:
            break

    camera.device_key = device_key

    db.commit()
    db.refresh(camera)

    return {
        "camera_id": camera.id,
        "device_key": device_key,
        "message": "Camera device key rotated successfully",
    }