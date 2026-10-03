from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    create_access_token,
    hash_password,
    verify_password,
)
from app.db.session import get_db
from app.models.entities import User
from app.schemas.common import (
    GoogleLoginRequest,
    LoginRequest,
    Token,
    UserCreate,
    UserOut,
)


router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)


# =========================================================
# REGISTER WITH EMAIL + PASSWORD
# =========================================================

@router.post(
    "/register",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
)
def register(
    payload: UserCreate,
    db: Session = Depends(get_db),
):
    email = payload.email.lower().strip()

    existing_user = db.scalar(
        select(User).where(User.email == email)
    )

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    user = User(
        name=payload.name,
        email=email,
        password_hash=hash_password(payload.password),
        auth_provider="local",
        google_sub=None,
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    return user


# =========================================================
# LOGIN WITH EMAIL + PASSWORD
# =========================================================

@router.post(
    "/login",
    response_model=Token,
)
def login(
    payload: LoginRequest,
    db: Session = Depends(get_db),
):
    email = payload.email.lower().strip()

    user = db.scalar(
        select(User).where(User.email == email)
    )

    if (
        not user
        or not user.password_hash
        or not verify_password(
            payload.password,
            user.password_hash,
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive",
        )

    return Token(
        access_token=create_access_token(user.id)
    )


# =========================================================
# OAUTH2 PASSWORD TOKEN
# =========================================================

@router.post(
    "/token",
    response_model=Token,
)
def token(
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    email = form.username.lower().strip()

    user = db.scalar(
        select(User).where(User.email == email)
    )

    if (
        not user
        or not user.password_hash
        or not verify_password(
            form.password,
            user.password_hash,
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive",
        )

    return Token(
        access_token=create_access_token(user.id)
    )


# =========================================================
# GOOGLE SIGN-IN
# =========================================================

@router.post(
    "/google",
    response_model=Token,
)
def google_login(
    payload: GoogleLoginRequest,
    db: Session = Depends(get_db),
):
    if not settings.google_client_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google authentication is not configured",
        )

    try:
        google_user = id_token.verify_oauth2_token(
            payload.credential,
            google_requests.Request(),
            settings.google_client_id,
        )

    except (ValueError, Exception):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Google authentication token",
        )

    google_sub = google_user.get("sub")
    google_email = google_user.get("email")
    email_verified = google_user.get("email_verified", False)

    if not google_sub or not google_email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google account information is incomplete",
        )

    if not email_verified:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google email address is not verified",
        )

    email = google_email.lower().strip()

    # First check whether this Google account was already linked.
    user = db.scalar(
        select(User).where(
            User.google_sub == google_sub
        )
    )

    # If it has never been linked, only allow an existing
    # KOLAPSE-approved email address.
    if not user:
        user = db.scalar(
            select(User).where(
                User.email == email
            )
        )

        if not user:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "This Google account is not authorized "
                    "to access KOLAPSE"
                ),
            )

        # Prevent a different Google identity from taking
        # over an account that is already linked.
        if (
            user.google_sub
            and user.google_sub != google_sub
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "This KOLAPSE account is already linked "
                    "to another Google account"
                ),
            )

        user.google_sub = google_sub

        # Keep password authentication available for users
        # who originally registered with a password.
        if user.password_hash:
            user.auth_provider = "local+google"
        else:
            user.auth_provider = "google"

        db.commit()
        db.refresh(user)

    # Make sure the Google identity still belongs to the
    # same authorized KOLAPSE email address.
    if user.email.lower() != email:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Google account does not match the authorized KOLAPSE account",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive",
        )

    return Token(
        access_token=create_access_token(user.id)
    )