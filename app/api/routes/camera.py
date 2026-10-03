import secrets
import threading
import time
from datetime import datetime, timedelta, timezone

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
)
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.camera.camera_service import camera_service
from app.core.security import (
    get_current_user,
    require_ai_key,
)
from app.db.session import get_db
from app.models.entities import (
    Camera,
    Elder,
    User,
)


router = APIRouter(
    prefix="/camera",
    tags=["Camera"],
)


# =========================================================
# TEMPORARY STREAM TOKENS
# =========================================================

STREAM_TOKEN_LIFETIME_MINUTES = 5

stream_tokens: dict[str, dict] = {}
stream_tokens_lock = threading.Lock()


def utcnow():
    return datetime.now(timezone.utc)


def clean_expired_stream_tokens():
    now = utcnow()

    with stream_tokens_lock:
        expired_tokens = [
            token
            for token, data in stream_tokens.items()
            if data["expires_at"] <= now
        ]

        for token in expired_tokens:
            stream_tokens.pop(token, None)


def create_stream_token(
    camera_id: int,
    user_id: int,
) -> tuple[str, datetime]:

    clean_expired_stream_tokens()

    token = secrets.token_urlsafe(32)

    expires_at = utcnow() + timedelta(
        minutes=STREAM_TOKEN_LIFETIME_MINUTES
    )

    with stream_tokens_lock:
        stream_tokens[token] = {
            "camera_id": camera_id,
            "user_id": user_id,
            "expires_at": expires_at,
        }

    return token, expires_at


def validate_stream_token(
    token: str,
    camera_id: int,
) -> bool:

    clean_expired_stream_tokens()

    with stream_tokens_lock:
        token_data = stream_tokens.get(token)

        if not token_data:
            return False

        if token_data["camera_id"] != camera_id:
            return False

        if token_data["expires_at"] <= utcnow():
            stream_tokens.pop(token, None)
            return False

    return True


# =========================================================
# FIND CAMERA FROM DEVICE KEY
# =========================================================

def get_device_camera(
    x_device_key: str | None,
    db: Session,
) -> Camera:

    if not x_device_key:
        raise HTTPException(
            status_code=401,
            detail="Missing camera device key",
        )

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

    return camera


# =========================================================
# CHECK CAREGIVER OWNS CAMERA
# =========================================================

def get_owned_camera(
    camera_id: int,
    current: User,
    db: Session,
) -> Camera:

    camera = db.scalar(
        select(Camera)
        .join(
            Elder,
            Camera.elder_id == Elder.id,
        )
        .where(
            Camera.id == camera_id,
            Camera.is_active.is_(True),
            Elder.caregiver_id == current.id,
        )
    )

    if not camera:
        raise HTTPException(
            status_code=404,
            detail="Camera not found",
        )

    return camera


# =========================================================
# CAMERA STREAM GENERATOR
# =========================================================

def generate_camera_stream(
    camera_id: int,
):

    while True:

        frame = camera_service.get_jpeg_frame(
            camera_id
        )

        if frame is None:
            time.sleep(0.05)
            continue

        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n"
            + frame
            + b"\r\n"
        )

        time.sleep(0.05)


# =========================================================
# RECEIVE FRAME FROM AI RUNNER
# =========================================================

@router.post("/frame")
async def receive_ai_frame(
    request: Request,
    x_ai_key: str | None = Header(
        default=None
    ),
    x_device_key: str | None = Header(
        default=None
    ),
    db: Session = Depends(get_db),
):

    # Verify KOLAPSE AI runner.
    require_ai_key(
        x_ai_key
    )

    # Identify the installed camera.
    camera = get_device_camera(
        x_device_key,
        db,
    )

    jpeg_bytes = await request.body()

    if not jpeg_bytes:
        return Response(
            content="Empty frame",
            status_code=400,
        )

    success = camera_service.update_jpeg(
        camera.id,
        jpeg_bytes,
    )

    if not success:
        return Response(
            content="Invalid JPEG frame",
            status_code=400,
        )

    return {
        "received": True,
        "camera_id": camera.id,
        "elder_id": camera.elder_id,
    }


# =========================================================
# CREATE TEMPORARY CAMERA VIEW TOKEN
# =========================================================

@router.post("/stream-token/{camera_id}")
def request_stream_token(
    camera_id: int,
    current: User = Depends(
        get_current_user
    ),
    db: Session = Depends(get_db),
):

    # This verifies that the logged-in caregiver
    # owns the elder connected to this camera.
    camera = get_owned_camera(
        camera_id,
        current,
        db,
    )

    token, expires_at = create_stream_token(
        camera_id=camera.id,
        user_id=current.id,
    )

    return {
        "camera_id": camera.id,
        "stream_token": token,
        "expires_at": expires_at.isoformat(),
        "expires_in_seconds": (
            STREAM_TOKEN_LIFETIME_MINUTES * 60
        ),
    }


# =========================================================
# SECURE CAMERA STREAM
# =========================================================

@router.get("/stream/{camera_id}")
def camera_stream(
    camera_id: int,
    stream_token: str = Query(...),
):

    valid = validate_stream_token(
        stream_token,
        camera_id,
    )

    if not valid:
        raise HTTPException(
            status_code=401,
            detail=(
                "Invalid or expired camera stream token"
            ),
        )

    return StreamingResponse(
        generate_camera_stream(
            camera_id
        ),
        media_type=(
            "multipart/x-mixed-replace; "
            "boundary=frame"
        ),
    )


# =========================================================
# CAMERA STATUS FOR CAREGIVER
# =========================================================

@router.get("/status/{camera_id}")
def camera_status(
    camera_id: int,
    current: User = Depends(
        get_current_user
    ),
    db: Session = Depends(get_db),
):

    camera = get_owned_camera(
        camera_id,
        current,
        db,
    )

    status = camera_service.get_status(
        camera.id
    )

    return {
        "camera_id": camera.id,
        "elder_id": camera.elder_id,
        "name": camera.name,
        "location": camera.location,
        "available": status["available"],
        "frame_count": status["frame_count"],
        "last_frame_age_seconds": status[
            "last_frame_age_seconds"
        ],
        "source": "KOLAPSE AI Camera",
    }


# =========================================================
# LIST CAMERAS FOR ONE ELDER
# =========================================================

@router.get("/elder/{elder_id}")
def elder_cameras(
    elder_id: int,
    current: User = Depends(
        get_current_user
    ),
    db: Session = Depends(get_db),
):

    # Verify caregiver owns the elder.
    elder = db.scalar(
        select(Elder).where(
            Elder.id == elder_id,
            Elder.caregiver_id == current.id,
        )
    )

    if not elder:
        raise HTTPException(
            status_code=404,
            detail="Elder not found",
        )

    cameras = list(
        db.scalars(
            select(Camera)
            .where(
                Camera.elder_id == elder_id,
                Camera.is_active.is_(True),
            )
            .order_by(Camera.id)
        )
    )

    # Never expose device_key to the browser.
    return [
        {
            "id": camera.id,
            "elder_id": camera.elder_id,
            "name": camera.name,
            "location": camera.location,
            "is_active": camera.is_active,
        }
        for camera in cameras
    ]