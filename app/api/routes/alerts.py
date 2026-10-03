from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.core.security import get_current_user
from app.db.session import get_db
from app.models.entities import Alert, AlertStatus, Elder, User
from app.schemas.common import AlertOut, AlertResolve

router = APIRouter(prefix="/alerts", tags=["Alerts"])


def owned_alert(alert_id: int, current: User, db: Session) -> Alert:
    alert = db.scalar(
        select(Alert).join(Elder, Alert.elder_id == Elder.id)
        .where(Alert.id == alert_id, Elder.caregiver_id == current.id)
    )
    if not alert:
        raise HTTPException(404, "Alert not found")
    return alert


@router.get("", response_model=list[AlertOut])
def list_alerts(
    status: AlertStatus | None = Query(default=None),
    limit: int = Query(100, ge=1, le=500),
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = select(Alert).join(Elder).where(Elder.caregiver_id == current.id)
    if status:
        stmt = stmt.where(Alert.status == status)
    return list(db.scalars(stmt.order_by(Alert.timestamp.desc()).limit(limit)))


@router.get("/stats")
def stats(current: User = Depends(get_current_user), db: Session = Depends(get_db)):
    base = select(Alert).join(Elder).where(Elder.caregiver_id == current.id).subquery()
    total = db.scalar(select(func.count()).select_from(base)) or 0
    unresolved = db.scalar(select(func.count()).select_from(base).where(base.c.status == AlertStatus.unresolved)) or 0
    resolved = total - unresolved
    avg_response = db.scalar(select(func.avg(base.c.response_time)).where(base.c.response_time.is_not(None)))
    return {"total": total, "unresolved": unresolved, "resolved": resolved, "avg_response_minutes": round(float(avg_response), 2) if avg_response is not None else None}


@router.put("/{alert_id}/resolve", response_model=AlertOut)
def resolve(alert_id: int, payload: AlertResolve, current: User = Depends(get_current_user), db: Session = Depends(get_db)):
    alert = owned_alert(alert_id, current, db)
    if alert.status == AlertStatus.unresolved:
        now = datetime.now(timezone.utc)
        alert.status = AlertStatus.resolved
        alert.resolved_at = now
        alert.response_time = max(0.0, (now - alert.timestamp).total_seconds() / 60.0)
    alert.notes = payload.notes
    db.commit()
    db.refresh(alert)
    return alert


@router.delete("/{alert_id}", status_code=204)
def delete(alert_id: int, current: User = Depends(get_current_user), db: Session = Depends(get_db)):
    alert = owned_alert(alert_id, current, db)
    db.delete(alert)
    db.commit()
    return Response(status_code=204)
