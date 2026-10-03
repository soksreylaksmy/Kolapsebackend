from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.security import get_current_user, hash_password
from app.db.session import get_db
from app.models.entities import User
from app.schemas.common import UserOut, UserUpdate

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/me", response_model=UserOut)
def me(current: User = Depends(get_current_user)):
    return current


@router.put("/me", response_model=UserOut)
def update_me(payload: UserUpdate, current: User = Depends(get_current_user), db: Session = Depends(get_db)):
    data = payload.model_dump(exclude_unset=True)
    password = data.pop("password", None)
    for key, value in data.items():
        setattr(current, key, value.lower() if key == "email" else value)
    if password:
        current.password_hash = hash_password(password)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(409, "Email already in use")
    db.refresh(current)
    return current
