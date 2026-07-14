"""Scheduled one-shot alerts: created from the Record → Alert tab, listed
in the bell panel, sent to the Telegram alert chat when due, then deleted.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Alert
from ..schemas import AlertIn, AlertOut, AlertPatch

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


def _naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.replace(tzinfo=None)


@router.post("", response_model=AlertOut, status_code=201)
def create_alert(payload: AlertIn, db: Session = Depends(get_db)):
    alert = Alert(due_time=_naive_utc(payload.due_time), message=payload.message)
    db.add(alert)
    db.commit()
    return alert


@router.get("", response_model=list[AlertOut])
def list_alerts(db: Session = Depends(get_db)):
    """Pending alerts, soonest first (sent ones are already deleted)."""
    return db.query(Alert).order_by(Alert.due_time.asc()).all()


@router.patch("/{alert_id}", response_model=AlertOut)
def patch_alert(alert_id: int, payload: AlertPatch, db: Session = Depends(get_db)):
    alert = db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(404, "Alert not found")
    data = payload.model_dump(exclude_unset=True)
    if "due_time" in data and data["due_time"] is not None:
        data["due_time"] = _naive_utc(data["due_time"])
    for field, value in data.items():
        setattr(alert, field, value)
    db.commit()
    return alert


@router.delete("/{alert_id}", status_code=204)
def delete_alert(alert_id: int, db: Session = Depends(get_db)):
    alert = db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(404, "Alert not found")
    db.delete(alert)
    db.commit()
