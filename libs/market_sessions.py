"""
market_sessions.py
==================
Timezone-aware FX session labelling and timestamp utilities.

Design principle
----------------
DST rules are NEVER hand-coded here. Session hours are defined in *local
wall-clock time* for each financial centre, and Python's `zoneinfo` module
(backed by the IANA tz database) performs every UTC <-> local conversion.
The IANA database encodes the full historical record — the 1918 Calder Act,
year-round US "War Time" (1942-45), the 1974 emergency DST, British Double
Summer Time (GMT+2), the 1968-71 British Standard Time experiment, the 1947
UK fuel-crisis schedule, Australia's WWI/WWII mandates, the 1967 Tasmanian
drought decoupling, the Sydney-2000 Olympics early start, the WA 2006-09
trial, Japan's occupation-era DST (1948-51), Hong Kong summer time (until
1979), Singapore's +7:30 -> +8:00 switch (1982-01-01), Switzerland's 1981
CEST adoption, and Berlin's 1945 CEMT (+3). See test_market_sessions.py,
which validates all of these against the database.

Everything accepts either scalars (datetime / pd.Timestamp) or pandas
Series / DatetimeIndex / DataFrame where noted, and is importable:

    from market_sessions import (
        Session, DEFAULT_SESSIONS, active_sessions, primary_session,
        label_sessions, make_naive, ensure_utc, utc_to_local, local_to_utc,
        day_of_week, month_of_year, is_dst, utc_offset_hours,
        dst_transitions, fx_market_is_open,
    )
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

UTC = timezone.utc

__all__ = [
    "Session", "DEFAULT_SESSIONS", "SESSION_PRIORITY", "SESSION_BY_NAME",
    "ensure_utc", "make_naive", "utc_to_local", "local_to_utc",
    "active_sessions", "primary_session", "session_name", "label_sessions",
    "day_of_week", "month_of_year", "is_dst", "utc_offset_hours",
    "dst_transitions", "fx_market_is_open", "add_calendar_columns",
    "pretty_session", "session_utc_window",
    "SEGMENT_CHAIN", "SEGMENT_LABEL", "segment_windows",
]

# --------------------------------------------------------------------------
# Session definitions (local wall-clock hours per financial centre)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Session:
    """A trading session defined in LOCAL wall-clock time.

    open/close are local times; close is exclusive. If close <= open the
    session is treated as wrapping past local midnight. Because hours are
    local, DST shifts (historical or modern) move the session's UTC
    footprint automatically — no per-era logic needed.
    """
    name: str
    tz: str          # IANA zone key, e.g. "Europe/London"
    open: time       # local open  (inclusive)
    close: time      # local close (exclusive)

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.tz)


# Conventional cash/FX desk hours per centre. All configurable: pass your
# own tuple of Session objects to any function that takes `sessions=`.
DEFAULT_SESSIONS: tuple[Session, ...] = (
    Session("Sydney",    "Australia/Sydney", time(7, 0),  time(16, 0)),
    Session("Tokyo",     "Asia/Tokyo",       time(9, 0),  time(18, 0)),
    Session("HongKong",  "Asia/Hong_Kong",   time(9, 0),  time(17, 0)),
    Session("Singapore", "Asia/Singapore",   time(9, 0),  time(17, 0)),
    Session("Frankfurt", "Europe/Berlin",    time(8, 0),  time(17, 0)),
    Session("Zurich",    "Europe/Zurich",    time(8, 0),  time(17, 0)),
    Session("London",    "Europe/London",    time(8, 0),  time(17, 0)),
    Session("NewYork",   "America/New_York", time(8, 0),  time(17, 0)),
)

# When several sessions overlap, `primary_session` picks the first active
# name in this order (the four majors first, then regional centres).
SESSION_PRIORITY: tuple[str, ...] = (
    "London", "NewYork", "Tokyo", "Sydney",
    "Frankfurt", "Zurich", "HongKong", "Singapore",
)


# --------------------------------------------------------------------------
# Scalar timestamp helpers
# --------------------------------------------------------------------------

def ensure_utc(ts) -> pd.Timestamp:
    """Return a tz-aware UTC Timestamp.

    Naive input is ASSUMED to already represent UTC (it is localized, not
    shifted). Aware input is converted to UTC (the instant is preserved).
    """
    t = pd.Timestamp(ts)
    return t.tz_localize(UTC) if t.tzinfo is None else t.tz_convert(UTC)


def make_naive(ts, *, keep_wall_clock: bool = False):
    """Strip timezone info from a timestamp, Series, or DatetimeIndex.

    keep_wall_clock=False (default): convert to UTC first, then drop tzinfo
        -> naive UTC. Safe default for storage/joins: the instant survives.
    keep_wall_clock=True: drop tzinfo in place -> the local clock reading
        survives but the absolute instant is lost.
    Already-naive input is returned unchanged.
    """
    if isinstance(ts, pd.Series):
        if ts.dt.tz is None:
            return ts
        return (ts if keep_wall_clock else ts.dt.tz_convert(UTC)).dt.tz_localize(None)
    if isinstance(ts, pd.DatetimeIndex):
        if ts.tz is None:
            return ts
        return (ts if keep_wall_clock else ts.tz_convert(UTC)).tz_localize(None)
    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        return t
    return (t if keep_wall_clock else t.tz_convert(UTC)).tz_localize(None)


def utc_to_local(ts, tz: str):
    """UTC -> local time in `tz` (any IANA zone, e.g. 'America/New_York').

    Naive input is assumed UTC. Works on scalars, Series, DatetimeIndex.
    Full historical DST rules apply automatically.
    """
    if isinstance(ts, pd.Series):
        s = ts if ts.dt.tz is not None else ts.dt.tz_localize(UTC)
        return s.dt.tz_convert(tz)
    if isinstance(ts, pd.DatetimeIndex):
        i = ts if ts.tz is not None else ts.tz_localize(UTC)
        return i.tz_convert(tz)
    return ensure_utc(ts).tz_convert(tz)


def local_to_utc(ts, tz: str, *, ambiguous: str = "earliest"):
    """Local wall-clock time in `tz` -> UTC.

    `ambiguous` handles the autumn fall-back hour that occurs twice:
    'earliest' (default) takes the first occurrence (DST), 'latest' the
    second (standard time). Nonexistent spring-forward times are shifted
    forward by the gap. Works on scalars, Series, DatetimeIndex.
    """
    # pandas semantics: ambiguous=True -> interpret as DST, which is the
    # FIRST ('earliest') occurrence of the repeated fall-back hour.
    amb = ambiguous == "earliest"
    if isinstance(ts, (pd.Series, pd.DatetimeIndex)):
        acc = ts.dt if isinstance(ts, pd.Series) else ts
        localized = acc.tz_localize(
            tz, ambiguous=np.full(len(ts), amb), nonexistent="shift_forward"
        )
        return localized.dt.tz_convert(UTC) if isinstance(ts, pd.Series) else localized.tz_convert(UTC)
    t = pd.Timestamp(ts)
    if t.tzinfo is not None:
        return t.tz_convert(UTC)
    return t.tz_localize(tz, ambiguous=amb, nonexistent="shift_forward").tz_convert(UTC)


# --------------------------------------------------------------------------
# Session identification — scalar API
# --------------------------------------------------------------------------

def _minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def _is_open(local: datetime, sess: Session, skip_weekends: bool) -> bool:
    if skip_weekends and local.weekday() >= 5:          # Sat=5, Sun=6 (local!)
        return False
    m, o, c = local.hour * 60 + local.minute, _minutes(sess.open), _minutes(sess.close)
    return (o <= m < c) if o < c else (m >= o or m < c)


def active_sessions(ts, sessions: Sequence[Session] = DEFAULT_SESSIONS,
                    *, skip_weekends: bool = True) -> list[str]:
    """All sessions open at a given UTC instant (naive input assumed UTC)."""
    t = ensure_utc(ts).to_pydatetime()
    return [s.name for s in sessions
            if _is_open(t.astimezone(s.zone), s, skip_weekends)]


def primary_session(ts, sessions: Sequence[Session] = DEFAULT_SESSIONS,
                    *, priority: Sequence[str] = SESSION_PRIORITY,
                    skip_weekends: bool = True) -> str:
    """Single label for an instant: highest-priority active session, else 'None'."""
    act = set(active_sessions(ts, sessions, skip_weekends=skip_weekends))
    for name in priority:
        if name in act:
            return name
    for name in act:                     # active session not in priority list
        return name
    return "None"


def session_name(ts, sessions: Sequence[Session] = DEFAULT_SESSIONS,
                 *, skip_weekends: bool = True) -> str:
    """Requirement 1: UTC timestamp -> session name(s), pipe-joined.

    e.g. 'London|NewYork' during the overlap, 'None' when nothing is open.
    """
    act = active_sessions(ts, sessions, skip_weekends=skip_weekends)
    return "|".join(act) if act else "None"


# --------------------------------------------------------------------------
# Session identification — vectorized DataFrame API
# --------------------------------------------------------------------------

def _as_utc_index(obj) -> pd.DatetimeIndex:
    idx = pd.DatetimeIndex(obj)
    return idx.tz_localize(UTC) if idx.tz is None else idx.tz_convert(UTC)


def label_sessions(df: pd.DataFrame, ts_col: str | None = None,
                   sessions: Sequence[Session] = DEFAULT_SESSIONS,
                   *, priority: Sequence[str] = SESSION_PRIORITY,
                   skip_weekends: bool = True, prefix: str = "sess_",
                   copy: bool = True) -> pd.DataFrame:
    """Requirement 2: mark every row of a dataset with its session(s).

    Timestamps come from `df[ts_col]` if given, else from `df.index`.
    Naive timestamps are assumed UTC. Adds, per session, a boolean column
    `{prefix}{Name}`, plus:
        session          pipe-joined active sessions ('None' if none)
        session_primary  single highest-priority label
        session_count    number of simultaneously open sessions

    Fully vectorized (one tz_convert per session), so it scales to
    tick-level frames.
    """
    out = df.copy() if copy else df
    idx = _as_utc_index(df[ts_col] if ts_col is not None else df.index)

    n = len(idx)
    masks: dict[str, np.ndarray] = {}
    for s in sessions:
        loc = idx.tz_convert(s.tz)
        m = loc.hour.values * 60 + loc.minute.values
        o, c = _minutes(s.open), _minutes(s.close)
        mask = (m >= o) & (m < c) if o < c else (m >= o) | (m < c)
        if skip_weekends:
            mask &= loc.weekday.values < 5          # weekend in LOCAL time
        masks[s.name] = mask
        out[f"{prefix}{s.name}"] = mask

    # pipe-joined label
    label = np.full(n, "", dtype=object)
    for s in sessions:
        label = np.where(masks[s.name], np.char.add(label.astype(str), s.name + "|"), label)
    label = np.char.rstrip(label.astype(str), "|")
    out["session"] = np.where(label == "", "None", label)

    # single primary label (assign lowest priority first, overwrite upward)
    prio = [p for p in priority if p in masks] + [k for k in masks if k not in priority]
    primary = np.full(n, "None", dtype=object)
    for name in reversed(prio):
        primary = np.where(masks[name], name, primary)
    out["session_primary"] = primary

    out["session_count"] = np.sum(list(masks.values()), axis=0).astype(int)
    return out


# --------------------------------------------------------------------------
# Calendar helpers (requirements 5 & 6)
# --------------------------------------------------------------------------

def day_of_week(ts, tz: str | None = None, *, as_name: bool = True):
    """Day of week. Scalar -> 'Monday' (or 0-6, Mon=0 if as_name=False);
    Series/DatetimeIndex -> vector of same. If `tz` is given, the day is
    evaluated in that zone's local time (a Friday 23:00 UTC is already
    Saturday in Sydney)."""
    if isinstance(ts, (pd.Series, pd.DatetimeIndex)):
        v = utc_to_local(ts, tz) if tz else ts
        acc = v.dt if isinstance(v, pd.Series) else v
        return acc.day_name() if as_name else (acc.dayofweek if not isinstance(v, pd.Series) else acc.dayofweek)
    t = utc_to_local(ts, tz) if tz else pd.Timestamp(ts)
    return t.day_name() if as_name else t.dayofweek


def month_of_year(ts, tz: str | None = None, *, as_name: bool = True):
    """Month of year. Scalar -> 'January' (or 1-12 if as_name=False);
    Series/DatetimeIndex -> vector of same. Evaluated in `tz` local time
    if given."""
    if isinstance(ts, (pd.Series, pd.DatetimeIndex)):
        v = utc_to_local(ts, tz) if tz else ts
        acc = v.dt if isinstance(v, pd.Series) else v
        return acc.month_name() if as_name else acc.month
    t = utc_to_local(ts, tz) if tz else pd.Timestamp(ts)
    return t.month_name() if as_name else t.month


def add_calendar_columns(df: pd.DataFrame, ts_col: str | None = None,
                         tz: str | None = None, *, copy: bool = True) -> pd.DataFrame:
    """Convenience: add dow (0-6), dow_name, month (1-12), month_name,
    hour_utc, date columns to a frame in one call."""
    out = df.copy() if copy else df
    idx = _as_utc_index(df[ts_col] if ts_col is not None else df.index)
    loc = idx.tz_convert(tz) if tz else idx
    out["dow"] = loc.dayofweek
    out["dow_name"] = loc.day_name()
    out["month"] = loc.month
    out["month_name"] = loc.month_name()
    out["hour_utc"] = idx.hour
    out["date"] = loc.date
    return out


# --------------------------------------------------------------------------
# DST / market-state utilities (requirement 7)
# --------------------------------------------------------------------------

def is_dst(ts, tz: str) -> bool:
    """True if `tz` is observing daylight saving at this UTC instant."""
    return bool(ensure_utc(ts).tz_convert(tz).dst())


def utc_offset_hours(ts, tz: str) -> float:
    """UTC offset (hours, may be fractional e.g. old Singapore +7.5) of
    `tz` at this UTC instant — full historical rules applied."""
    return ensure_utc(ts).tz_convert(tz).utcoffset().total_seconds() / 3600.0


def dst_transitions(tz: str, year: int) -> list[tuple[pd.Timestamp, float, float]]:
    """All UTC-offset changes in `tz` during `year` (DST shifts, and also
    base-offset moves like Singapore 1982). Returns (utc_instant,
    offset_before_h, offset_after_h), instant accurate to the minute."""
    zone = ZoneInfo(tz)
    start = datetime(year, 1, 1, tzinfo=UTC)
    end = datetime(year + 1, 1, 1, tzinfo=UTC)
    step = timedelta(hours=1)
    res: list[tuple[pd.Timestamp, float, float]] = []
    prev_t, prev_off = start, start.astimezone(zone).utcoffset()
    t = start + step
    while t <= end:
        off = t.astimezone(zone).utcoffset()
        if off != prev_off:
            lo, hi = prev_t, t                       # bisect to the minute
            while hi - lo > timedelta(minutes=1):
                mid = lo + (hi - lo) / 2
                mid = mid.replace(second=0, microsecond=0)
                if mid <= lo:
                    mid += timedelta(minutes=1)
                if mid.astimezone(zone).utcoffset() == prev_off:
                    lo = mid
                else:
                    hi = mid
            res.append((pd.Timestamp(hi), prev_off.total_seconds() / 3600,
                        off.total_seconds() / 3600))
        prev_t, prev_off = t, off
        t += step
    return res


# --------------------------------------------------------------------------
# Session UTC windows & the five-part trading-day partition
# (the ONE shared implementation — server/marketdata.py and the strategies
#  import from here, so every consumer applies identical DST-correct maths)
# --------------------------------------------------------------------------

SESSION_BY_NAME: dict[str, Session] = {s.name: s for s in DEFAULT_SESSIONS}

# Display names for session keys ("NewYork" → "New York").
PRETTY_SESSION = {"NewYork": "New York"}


def pretty_session(name: str) -> str:
    return PRETTY_SESSION.get(name, name)


def session_utc_window(name: str, day: date) -> tuple[pd.Timestamp, pd.Timestamp]:
    """One session's [open, close) as naive UTC for a local anchor date.

    The session is defined in local wall-clock time, so converting each
    anchor date separately applies that date's DST rules exactly.
    """
    s = SESSION_BY_NAME[name]
    lo = local_to_utc(datetime.combine(day, s.open), s.tz)
    hi = local_to_utc(datetime.combine(day, s.close), s.tz)
    return lo.tz_localize(None), hi.tz_localize(None)


# The five-part partition of one trading day, in day order: each consecutive
# pair is an (analyze, trigger) transition for the σ-band work.
SEGMENT_CHAIN = ["tokyo_solo", "tokyo_london", "london_solo", "london_ny", "ny_solo"]
SEGMENT_LABEL = {
    "tokyo_solo": "Tokyo (solo)", "tokyo_london": "Tokyo ∩ London",
    "london_solo": "London (solo)", "london_ny": "London ∩ NY",
    "ny_solo": "New York (solo)",
}


def segment_windows(day: date) -> dict[str, tuple[pd.Timestamp, pd.Timestamp]]:
    """The five-part partition of one trading day, naive-UTC, DST-correct."""
    tk_o, tk_c = session_utc_window("Tokyo", day)
    ln_o, ln_c = session_utc_window("London", day)
    ny_o, ny_c = session_utc_window("NewYork", day)
    return {
        "tokyo_solo":   (tk_o, ln_o),
        "tokyo_london": (ln_o, tk_c),
        "london_solo":  (tk_c, ny_o),
        "london_ny":    (ny_o, ln_c),
        "ny_solo":      (ln_c, ny_c),
    }


def fx_market_is_open(ts) -> bool:
    """Spot FX weekly open/close: market closes Friday 17:00 New York time
    and reopens Sunday 17:00 New York time. Defined in NY local time so the
    UTC boundary (21:00 vs 22:00 UTC) shifts correctly with US DST."""
    ny = ensure_utc(ts).tz_convert("America/New_York")
    wd, m = ny.weekday(), ny.hour * 60 + ny.minute
    if wd == 5:                                   # Saturday
        return False
    if wd == 4 and m >= 17 * 60:                  # Friday from 17:00 NY
        return False
    if wd == 6 and m < 17 * 60:                   # Sunday before 17:00 NY
        return False
    return True