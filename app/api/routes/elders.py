from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.security import get_current_user
from app.db.session import get_db
from app.models.entities import Elder, User
from app.schemas.common import ElderCreate, ElderOut, ElderUpdate

router = APIRouter(prefix="/elders", tags=["Elders"])


def owned_elder(elder_id: int, current: User, db: Session) -> Elder:
    elder = db.scalar(select(Elder).where(Elder.id == elder_id, Elder.caregiver_id == current.id))
    if not elder:
        raise HTTPException(404, "Elder not found")
    return elder


@router.get("", response_model=list[ElderOut])
def list_elders(current: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return list(db.scalars(select(Elder).where(Elder.caregiver_id == current.id).order_by(Elder.created_at.desc())))


@router.post("", response_model=ElderOut, status_code=201)
def create_elder(payload: ElderCreate, current: User = Depends(get_current_user), db: Session = Depends(get_db)):
    elder = Elder(caregiver_id=current.id, **payload.model_dump())
    db.add(elder)
    db.commit()
    db.refresh(elder)
    return elder


@router.get("/{elder_id}", response_model=ElderOut)
def get_elder(elder_id: int, current: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return owned_elder(elder_id, current, db)


@router.put("/{elder_id}", response_model=ElderOut)
def update_elder(elder_id: int, payload: ElderUpdate, current: User = Depends(get_current_user), db: Session = Depends(get_db)):
    elder = owned_elder(elder_id, current, db)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(elder, key, value)
    db.commit()
    db.refresh(elder)
    return elder


@router.delete("/{elder_id}", status_code=204)
def delete_elder(elder_id: int, current: User = Depends(get_current_user), db: Session = Depends(get_db)):
    elder = owned_elder(elder_id, current, db)
    db.delete(elder)
    db.commit()
    return Response(status_code=204)
