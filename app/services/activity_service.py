from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models.entities import ActivityLog, Alert, AlertStatus, Elder, Severity
from app.schemas.common import ActivityCreate


def record_activity(db: Session, payload: ActivityCreate) -> tuple[ActivityLog, Alert | None, Elder]:
    elder = db.get(Elder, payload.elder_id)
    if elder is None:
        raise ValueError("Elder not found")

    log = ActivityLog(**payload.model_dump())
    db.add(log)
    db.flush()

    alert = None
    is_fall = payload.activity.value == "falling" and payload.confidence >= settings.fall_confidence_threshold
    if is_fall:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.fall_alert_cooldown_seconds)
        recent = db.scalar(
            select(Alert)
            .where(
                Alert.elder_id == payload.elder_id,
                Alert.status == AlertStatus.unresolved,
                Alert.timestamp >= cutoff,
            )
            .order_by(Alert.timestamp.desc())
        )
        if recent is None:
            alert = Alert(
                elder_id=payload.elder_id,
                activity_log_id=log.id,
                severity=Severity.high,
            )
            db.add(alert)
            db.flush()

    db.commit()
    db.refresh(log)
    if alert:
        db.refresh(alert)
    return log, alert, elder
