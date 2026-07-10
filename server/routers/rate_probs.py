"""FOMC rate probabilities: paste-parse-store, and today/previous snapshots."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import RateProb, RateSnapshot
from ..rate_table import RateTableError, parse_rate_table
from ..schemas import RateProbOut, RateSnapshotOut, RateTableIn

router = APIRouter(prefix="/api/rate-probs", tags=["rate-probs"])


def _snapshot_out(snap: RateSnapshot) -> RateSnapshotOut:
    return RateSnapshotOut(
        id=snap.id,
        captured_at=snap.captured_at,
        probs=[
            RateProbOut(
                meeting_date=p.meeting_date,
                bucket=f"{p.bucket_low}-{p.bucket_high}",
                probability=p.probability,
            )
            for p in sorted(snap.probs, key=lambda p: (p.meeting_date, p.bucket_low))
        ],
    )


@router.post("", response_model=RateSnapshotOut, status_code=201)
def record_table(payload: RateTableIn, db: Session = Depends(get_db)):
    try:
        rows = parse_rate_table(payload.table)
    except RateTableError as e:
        raise HTTPException(422, str(e))
    snap = RateSnapshot()
    snap.probs = [
        RateProb(meeting_date=meeting, bucket_low=low, bucket_high=high,
                 probability=prob)
        for meeting, low, high, prob in rows
    ]
    db.add(snap)
    db.commit()
    return _snapshot_out(snap)


def _latest_on_or_before(db: Session, end: datetime) -> RateSnapshot | None:
    return (
        db.query(RateSnapshot)
        .filter(RateSnapshot.captured_at < end)
        .order_by(RateSnapshot.captured_at.desc())
        .first()
    )


@router.get("/latest", response_model=RateSnapshotOut | None)
def latest(db: Session = Depends(get_db)):
    """Today's (most recent) snapshot."""
    snap = _latest_on_or_before(db, datetime.max)
    return _snapshot_out(snap) if snap else None


@router.get("/previous-day", response_model=RateSnapshotOut | None)
def previous_day(db: Session = Depends(get_db)):
    """Most recent snapshot captured before today (UTC) — for comparison."""
    today = datetime.now(timezone.utc).replace(
        tzinfo=None, hour=0, minute=0, second=0, microsecond=0)
    snap = _latest_on_or_before(db, today)
    return _snapshot_out(snap) if snap else None
