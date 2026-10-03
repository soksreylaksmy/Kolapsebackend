from sqlalchemy import func, select
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.security import get_current_user
from app.db.session import get_db
from app.models.entities import Alert, AlertStatus, Elder, User

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/stats")
def dashboard_stats(current: User = Depends(get_current_user), db: Session = Depends(get_db)):
    elder_ids = select(Elder.id).where(Elder.caregiver_id == current.id)
    elder_count = db.scalar(select(func.count(Elder.id)).where(Elder.caregiver_id == current.id)) or 0
    total_alerts = db.scalar(select(func.count(Alert.id)).where(Alert.elder_id.in_(elder_ids))) or 0
    unresolved_alerts = db.scalar(select(func.count(Alert.id)).where(Alert.elder_id.in_(elder_ids), Alert.status == AlertStatus.unresolved)) or 0
    return {
        "elders": elder_count,
        "alerts_total": total_alerts,
        "alerts_unresolved": unresolved_alerts,
        "alerts_resolved": total_alerts - unresolved_alerts,
    }
