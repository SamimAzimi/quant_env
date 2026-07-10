"""VIX, Fear & Greed, Analyze & Thoughts, and Economic Reports recording.

The Stats page uses the strict previous-UTC-day rule: sentiment endpoints
return readings whose timestamp fell on the previous calendar day (UTC).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import EconReport, FearGreedReading, Thought, VixReading
from ..schemas import (
    EconReportIn, EconReportOut, EconReportPatch,
    ReadingIn, ReadingOut, ThoughtIn, ThoughtOut,
)

router = APIRouter(prefix="/api", tags=["records"])


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _naive_utc(dt: datetime | None) -> datetime:
    if dt is None:
        return _now()
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.replace(tzinfo=None)


def _prev_day_bounds() -> tuple[datetime, datetime]:
    today = _now().replace(hour=0, minute=0, second=0, microsecond=0)
    return today - timedelta(days=1), today


def _prev_day(db: Session, model):
    start, end = _prev_day_bounds()
    return (
        db.query(model)
        .filter(model.ts >= start, model.ts < end)
        .order_by(model.ts.desc())
        .all()
    )


# --- VIX -------------------------------------------------------------------

@router.post("/vix", response_model=ReadingOut, status_code=201)
def record_vix(payload: ReadingIn, db: Session = Depends(get_db)):
    reading = VixReading(ts=_naive_utc(payload.ts), value=payload.value)
    db.add(reading)
    db.commit()
    return reading


@router.get("/vix/previous-day", response_model=list[ReadingOut])
def vix_previous_day(db: Session = Depends(get_db)):
    return _prev_day(db, VixReading)


# --- Fear & Greed ------------------------------------------------------------

@router.post("/fear-greed", response_model=ReadingOut, status_code=201)
def record_fear_greed(payload: ReadingIn, db: Session = Depends(get_db)):
    if not 0 <= payload.value <= 100:
        raise HTTPException(422, "Fear & Greed must be between 0 and 100")
    reading = FearGreedReading(ts=_naive_utc(payload.ts), value=payload.value)
    db.add(reading)
    db.commit()
    return reading


@router.get("/fear-greed/previous-day", response_model=list[ReadingOut])
def fear_greed_previous_day(db: Session = Depends(get_db)):
    return _prev_day(db, FearGreedReading)


# --- Analyze & Thoughts -------------------------------------------------------

@router.post("/thoughts", response_model=ThoughtOut, status_code=201)
def record_thought(payload: ThoughtIn, db: Session = Depends(get_db)):
    thought = Thought(ts=_naive_utc(payload.ts), body=payload.body)
    db.add(thought)
    db.commit()
    return thought


@router.get("/thoughts", response_model=list[ThoughtOut])
def list_thoughts(limit: int = 50, db: Session = Depends(get_db)):
    return db.query(Thought).order_by(Thought.ts.desc()).limit(limit).all()


# --- Economic reports ---------------------------------------------------------

@router.post("/econ-reports", response_model=EconReportOut, status_code=201)
def record_econ_report(payload: EconReportIn, db: Session = Depends(get_db)):
    report = EconReport(**payload.model_dump())
    db.add(report)
    db.commit()
    return report


@router.get("/econ-reports", response_model=list[EconReportOut])
def list_econ_reports(pending: bool = False, db: Session = Depends(get_db)):
    """All recent reports; pending=true → only ones missing actual/outcome."""
    q = db.query(EconReport)
    if pending:
        q = q.filter(EconReport.outcome.is_(None))
    return q.order_by(EconReport.created_at.desc()).limit(100).all()


@router.patch("/econ-reports/{report_id}", response_model=EconReportOut)
def patch_econ_report(report_id: int, payload: EconReportPatch,
                      db: Session = Depends(get_db)):
    report = db.get(EconReport, report_id)
    if not report:
        raise HTTPException(404, "Report not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(report, field, value)
    db.commit()
    return report
