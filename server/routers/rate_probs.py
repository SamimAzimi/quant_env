"""FOMC rate probabilities: paste-parse-store, day snapshots, and history."""
from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..dates import as_of_or_today, day_bounds, range_bounds
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
def latest(date_: date | None = Query(None, alias="date"),
           db: Session = Depends(get_db)):
    """Most recent snapshot as of the selected day (default: now)."""
    if date_ is None:
        snap = _latest_on_or_before(db, datetime.max)
    else:
        _, end = day_bounds(date_)
        snap = _latest_on_or_before(db, end)
    return _snapshot_out(snap) if snap else None


@router.get("/previous-day", response_model=RateSnapshotOut | None)
def previous_day(date_: date | None = Query(None, alias="date"),
                 db: Session = Depends(get_db)):
    """Most recent snapshot captured before the selected day — comparison."""
    start, _ = day_bounds(as_of_or_today(date_))
    snap = _latest_on_or_before(db, start)
    return _snapshot_out(snap) if snap else None


@router.get("/history")
def history(start: date | None = None, end: date | None = None,
            buckets: int = 3, db: Session = Depends(get_db)):
    """Evolution of the nearest meeting's top rate buckets over time.

    One point per snapshot in the range; buckets are the top-N (by latest
    probability) for the earliest still-upcoming meeting, so the chart shows
    how expectations for the next FOMC decision shifted day by day.
    """
    s, e = range_bounds(start, end)
    snaps = (
        db.query(RateSnapshot)
        .filter(RateSnapshot.captured_at >= s, RateSnapshot.captured_at < e)
        .order_by(RateSnapshot.captured_at.asc())
        .all()
    )
    if not snaps:
        return {"meeting_date": None, "buckets": [], "series": []}

    latest_snap = snaps[-1]
    meeting = min(p.meeting_date for p in latest_snap.probs)
    top = sorted(
        (p for p in latest_snap.probs if p.meeting_date == meeting),
        key=lambda p: p.probability, reverse=True,
    )[:max(1, buckets)]
    keys = [(p.bucket_low, p.bucket_high) for p in top]

    series = []
    for snap in snaps:
        by_bucket = {(p.bucket_low, p.bucket_high): p.probability
                     for p in snap.probs if p.meeting_date == meeting}
        series.append({
            "captured_at": snap.captured_at.isoformat(),
            "probs": {f"{lo}-{hi}": by_bucket.get((lo, hi)) for lo, hi in keys},
        })
    return {
        "meeting_date": meeting.isoformat(),
        "buckets": [f"{lo}-{hi}" for lo, hi in keys],
        "series": series,
    }
