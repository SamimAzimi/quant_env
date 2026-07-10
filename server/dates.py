"""Shared date helpers for the as-of date selector and history filters.

The website's date picker sends `date=YYYY-MM-DD`; every "today/yesterday"
endpoint treats that date as *today*, so the whole page replays that day.
Recorded data (news, readings, trades) is bucketed by UTC calendar day.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone


def today_utc() -> date:
    return datetime.now(timezone.utc).date()


def as_of_or_today(as_of: date | None) -> date:
    return as_of or today_utc()


def day_bounds(day: date) -> tuple[datetime, datetime]:
    """[start, end) naive-UTC datetimes covering one calendar day."""
    start = datetime(day.year, day.month, day.day)
    return start, start + timedelta(days=1)


def range_bounds(start: date | None, end: date | None) -> tuple[datetime, datetime]:
    """[start, end] dates → [start 00:00, end+1 00:00) datetimes.

    Defaults: last 30 days up to today.
    """
    end = end or today_utc()
    start = start or (end - timedelta(days=30))
    s, _ = day_bounds(start)
    _, e = day_bounds(end)
    return s, e
