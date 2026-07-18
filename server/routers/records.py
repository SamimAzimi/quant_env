"""VIX, Fear & Greed, Analyze & Thoughts, and Economic Reports recording.

The Market Prep page uses the strict previous-day rule: sentiment endpoints
return readings from the day before the selected date (default: today, UTC).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..dates import as_of_or_today, day_bounds, range_bounds
from ..db import get_db
from ..utils import naive_utc
from ..models import EconReport, FearGreedReading, Thought, VixReading
from ..schemas import (
    EconReportIn, EconReportOut, EconReportPatch,
    ReadingIn, ReadingOut, ThoughtIn, ThoughtOut,
)

router = APIRouter(prefix="/api", tags=["records"])


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _naive_utc(dt: datetime | None) -> datetime:
    # shared conversion (server/utils.py); this router defaults None → _now()
    if dt is None:
        return _now()
    return naive_utc(dt)


def _prev_day(db: Session, model, as_of: date | None):
    """Readings for the "tomorrow" view: the day before the selected date
    AND the selected date itself, newest first.

    Prep data is usually recorded the evening before, but sometimes only
    on the morning itself — so same-day recordings show too, and being
    newer they win the top spot.
    """
    day = as_of_or_today(as_of)
    start, _ = day_bounds(day - timedelta(days=1))
    _, end = day_bounds(day)
    return (
        db.query(model)
        .filter(model.ts >= start, model.ts < end)
        .order_by(model.ts.desc())
        .all()
    )


def _range(db: Session, model, start: date | None, end: date | None):
    s, e = range_bounds(start, end)
    return (
        db.query(model)
        .filter(model.ts >= s, model.ts < e)
        .order_by(model.ts.asc())
        .limit(5000)
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
def vix_previous_day(date_: date | None = Query(None, alias="date"),
                     db: Session = Depends(get_db)):
    return _prev_day(db, VixReading, date_)


@router.get("/vix/history", response_model=list[ReadingOut])
def vix_history(start: date | None = None, end: date | None = None,
                db: Session = Depends(get_db)):
    """All VIX readings in the range (default last 30d), oldest first."""
    return _range(db, VixReading, start, end)


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
def fear_greed_previous_day(date_: date | None = Query(None, alias="date"),
                            db: Session = Depends(get_db)):
    return _prev_day(db, FearGreedReading, date_)


@router.get("/fear-greed/history", response_model=list[ReadingOut])
def fear_greed_history(start: date | None = None, end: date | None = None,
                       db: Session = Depends(get_db)):
    return _range(db, FearGreedReading, start, end)


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
def list_econ_reports(date_: date | None = Query(None, alias="date"),
                      pending: bool = False, db: Session = Depends(get_db)):
    """Reports recorded on the selected day (default: today).

    When viewing today, still-pending reports (no outcome yet) from earlier
    days stay visible so nothing unreleased disappears before it's filled
    in. pending=true → only reports missing an outcome, regardless of day.
    """
    if pending:
        return (db.query(EconReport).filter(EconReport.outcome.is_(None))
                .order_by(EconReport.created_at.desc()).limit(100).all())
    day = as_of_or_today(date_)
    start, end = day_bounds(day)
    cond = EconReport.created_at.between(start, end)
    if day == as_of_or_today(None):    # live today: keep older pending ones
        from sqlalchemy import or_
        cond = or_(cond, EconReport.outcome.is_(None))
    return (db.query(EconReport).filter(cond)
            .order_by(EconReport.created_at.desc()).limit(100).all())


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
