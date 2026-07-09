"""
test_market_sessions.py
=======================
Validates market_sessions.py against the documented historical DST record
for the US, London, Australia, Tokyo, Hong Kong, Singapore, Zurich and
Frankfurt, then exercises every functional requirement.

Run with pytest:   pytest test_market_sessions.py -v
Run standalone:    python test_market_sessions.py
"""
from datetime import time

import numpy as np
import pandas as pd

from libs.market_sessions import (
    DEFAULT_SESSIONS, active_sessions, add_calendar_columns, day_of_week,
    dst_transitions, ensure_utc, fx_market_is_open, is_dst, label_sessions,
    local_to_utc, make_naive, month_of_year, primary_session, session_name,
    utc_offset_hours, utc_to_local,
)


def off(tz: str, iso: str) -> float:
    """UTC offset in hours of `tz` at a UTC instant."""
    return utc_offset_hours(iso, tz)


def _check_offsets(tz: str, cases: list[tuple[str, float, str]]) -> None:
    for iso, expected, desc in cases:
        got = off(tz, iso)
        assert got == expected, (
            f"{tz} @ {iso} UTC ({desc}): expected UTC{expected:+.2f}, got UTC{got:+.2f}"
        )


# ===========================================================================
# 1. Historical DST record — United States (America/New_York)
# ===========================================================================

def test_us_dst_history():
    _check_offsets("America/New_York", [
        # 1918 Calder Act: DST Mar 31 -> Oct 27 1918
        ("1918-03-30T12:00", -5.0, "pre-Calder standard time"),
        ("1918-04-01T12:00", -4.0, "Calder Act DST active (start Mar 31)"),
        ("1918-10-28T12:00", -5.0, "after Oct 27 fall-back"),
        # WWII year-round War Time: Feb 9 1942 -> Sep 30 1945
        ("1942-02-08T12:00", -5.0, "day before War Time"),
        ("1942-02-10T12:00", -4.0, "Eastern War Time begins Feb 9 1942"),
        ("1943-01-15T12:00", -4.0, "EWT holds through winter"),
        ("1945-10-15T12:00", -5.0, "after War Time ends Sep 30 1945"),
        # 1974-75 emergency energy DST: Jan 6 1974; 1975 window Feb 23 -> Oct 26
        ("1973-01-15T12:00", -5.0, "normal winter (control)"),
        ("1974-01-07T12:00", -4.0, "emergency DST in January (from Jan 6)"),
        ("1975-02-01T12:00", -5.0, "1975 before Feb 23 start"),
        ("1975-03-01T12:00", -4.0, "inside shortened 1975 window"),
        # 1986 amendment: first Sunday of April from 1987
        ("1987-03-30T12:00", -5.0, "before first-Sun-Apr"),
        ("1987-04-06T12:00", -4.0, "after Apr 5 1987 spring-forward"),
        # Energy Policy Act 2005: second Sunday of March from 2007
        ("2006-03-20T12:00", -5.0, "old rule still standard in Mar 2006"),
        ("2007-03-12T12:00", -4.0, "new rule already DST (Mar 11 2007)"),
    ])


# ===========================================================================
# 2. Historical DST record — London (Europe/London)
# ===========================================================================

def test_london_dst_history():
    _check_offsets("Europe/London", [
        # First BST: May 21 1916 -> Oct 1 1916
        ("1916-05-20T12:00", 0.0, "pre-BST GMT"),
        ("1916-05-22T12:00", 1.0, "first BST (May 21 1916)"),
        ("1916-10-02T12:00", 0.0, "after Oct 1 1916 end"),
        # WWII: no fall-back autumn 1940; BDST GMT+2 from May 4 1941
        ("1941-01-15T12:00", 1.0, "winter 1940/41 stayed GMT+1"),
        ("1941-06-01T12:00", 2.0, "British Double Summer Time"),
        ("1945-08-01T12:00", 1.0, "BDST ended Jul 15 1945"),
        ("1945-11-15T12:00", 0.0, "back on GMT from Oct 7 1945"),
        # 1947 fuel crisis: +1 Mar 16, +2 Apr 13, +1 Aug 10, GMT Nov 2
        ("1947-03-20T12:00", 1.0, "fuel crisis GMT+1 (Mar 16)"),
        ("1947-05-01T12:00", 2.0, "fuel crisis GMT+2 (Apr 13)"),
        ("1947-09-01T12:00", 1.0, "dropped to +1 (Aug 10)"),
        ("1947-11-15T12:00", 0.0, "back to GMT (Nov 2)"),
        # British Standard Time experiment. NOTE: the source doc says the
        # 1968 shift was Sun Mar 18 1968; IANA (and timeanddate) record
        # Sun FEB 18 1968 — the document is wrong.
        ("1968-02-17T12:00", 0.0, "before early-1968 shift"),
        ("1968-02-19T12:00", 1.0, "shift was Feb 18 1968 (doc says Mar 18)"),
        ("1969-01-15T12:00", 1.0, "year-round GMT+1"),
        ("1970-12-25T12:00", 1.0, "experiment mid-winter +1"),
        ("1971-12-25T12:00", 0.0, "GMT restored after Oct 31 1971"),
        # Modern rule: last Sunday of March / last Sunday of October
        ("2024-03-30T12:00", 0.0, "day before last-Sun-Mar"),
        ("2024-04-01T12:00", 1.0, "modern BST"),
    ])


def test_london_modern_transition_instants():
    # 1998 EU harmonization: both shifts occur at 01:00 UTC exactly.
    tr = dst_transitions("Europe/London", 2024)
    assert str(tr[0][0]) == "2024-03-31 01:00:00+00:00", tr[0]
    assert str(tr[1][0]) == "2024-10-27 01:00:00+00:00", tr[1]
    assert (tr[0][1], tr[0][2]) == (0.0, 1.0)
    assert (tr[1][1], tr[1][2]) == (1.0, 0.0)


# ===========================================================================
# 3. Historical DST record — Australia
# ===========================================================================

def test_australia_dst_history():
    _check_offsets("Australia/Sydney", [
        # WWI: mainland from Jan 1 1917, repealed late 1917
        ("1916-12-15T12:00", 10.0, "pre-WWI-DST"),
        ("1917-01-15T12:00", 11.0, "WWI DST from Jan 1 1917"),
        ("1917-06-15T12:00", 10.0, "after repeal"),
        # WWII: nationwide from Jan 1 1942
        ("1942-01-15T12:00", 11.0, "WWII DST"),
        # Tasmania decoupled Oct 1 1967; Sydney did NOT move
        ("1967-10-15T12:00", 10.0, "Sydney not shifted while Hobart was"),
        # 1971 multi-state trial from Oct 31 1971
        ("1970-12-15T12:00", 10.0, "summer 1970, still no DST"),
        ("1971-09-15T12:00", 10.0, "1971 before Oct 31 start"),
        ("1971-11-15T12:00", 11.0, "in the 1971 trial"),
        ("1972-12-15T12:00", 11.0, "Sydney kept DST after trial"),
        # Sydney 2000 Olympics: early start Aug 27 2000
        ("1999-09-15T12:00", 10.0, "normal year: standard time mid-Sep"),
        ("2000-09-15T12:00", 11.0, "Olympics early DST"),
        # Modern harmonized rule: first Sun Oct -> first Sun Apr
        ("2024-09-25T12:00", 10.0, "before first-Sun-Oct"),
        ("2024-10-10T12:00", 11.0, "modern AEDT"),
        ("2025-04-10T12:00", 10.0, "after first-Sun-Apr end"),
    ])
    _check_offsets("Australia/Hobart", [
        ("1967-09-15T12:00", 10.0, "Tasmania before drought DST"),
        ("1967-10-15T12:00", 11.0, "Tasmania drought DST (Oct 1 1967)"),
    ])
    _check_offsets("Australia/Brisbane", [
        ("1971-11-15T12:00", 11.0, "QLD in the 1971 trial"),
        ("1972-12-15T12:00", 10.0, "QLD abandoned DST in 1972"),
        ("2024-10-10T12:00", 10.0, "QLD never shifts today"),
    ])
    _check_offsets("Australia/Perth", [
        ("2006-11-15T12:00", 8.0, "WA before trial (Dec 3 2006)"),
        ("2007-01-15T12:00", 9.0, "WA trial DST"),
        ("2010-01-15T12:00", 8.0, "WA after 2009 'No' referendum"),
    ])


# ===========================================================================
# 4. Historical record — Tokyo / Hong Kong / Singapore / Zurich / Frankfurt
# ===========================================================================

def test_asia_and_europe_history():
    _check_offsets("Asia/Tokyo", [
        ("1948-07-01T12:00", 10.0, "occupation-era DST 1948-51"),
        ("1949-01-15T12:00", 9.0, "winter standard"),
        ("1952-07-01T12:00", 9.0, "DST abolished"),
        ("2024-07-01T12:00", 9.0, "modern, no DST"),
    ])
    _check_offsets("Asia/Hong_Kong", [
        ("1975-07-01T12:00", 9.0, "HK summer time era"),
        ("1975-01-15T12:00", 8.0, "HK winter"),
        ("1985-07-01T12:00", 8.0, "HK DST gone (last observed 1979)"),
    ])
    _check_offsets("Asia/Singapore", [
        ("1981-12-15T12:00", 7.5, "old +7:30 offset"),
        ("1982-01-15T12:00", 8.0, "moved to +8 on Jan 1 1982"),
    ])
    _check_offsets("Europe/Zurich", [
        ("1941-07-01T12:00", 2.0, "Swiss wartime DST"),
        ("1980-07-01T12:00", 1.0, "pre-adoption: no DST"),
        ("1981-07-01T12:00", 2.0, "CEST adopted 1981"),
    ])
    _check_offsets("Europe/Berlin", [
        ("1916-06-01T12:00", 2.0, "world's first DST (Apr 30 1916)"),
        ("1945-07-01T12:00", 3.0, "Berlin CEMT triple time"),
        ("1979-07-01T12:00", 1.0, "no DST yet in 1979"),
        ("1980-07-01T12:00", 2.0, "DST resumed 1980"),
    ])


# ===========================================================================
# 5. Requirement 1 — UTC timestamp -> session name (incl. historical eras)
# ===========================================================================

def test_session_name_scalar():
    # Modern winter: London 08:00 local == 08:00 UTC
    assert "London" not in active_sessions("2024-01-15T07:30")
    assert "London" in active_sessions("2024-01-15T08:30")
    # Modern summer: London opens 07:00 UTC under BST
    assert "London" in active_sessions("2024-07-15T07:30")
    # London/NY overlap in winter
    assert session_name("2024-01-15T14:00") == "Frankfurt|Zurich|London|NewYork"
    assert primary_session("2024-01-15T14:00") == "London"
    # Mon 23:30 UTC = Tue 10:30 AEDT: only Sydney is open (NY closed 22:00 UTC).
    # Note: the 8 default sessions cover all 24 weekday hours, so 'None'
    # only occurs on weekends (see test_weekend_is_local).
    assert session_name("2024-01-15T23:30") == "Sydney"


def test_session_name_historical_eras():
    # NY open = 08:00 local. Jan 1973 (EST, -5) -> 13:00 UTC.
    # Jan 1974 (emergency DST, -4) -> 12:00 UTC. Same UTC clock, different era:
    assert "NewYork" not in active_sessions("1973-01-16T12:30")
    assert "NewYork" in active_sessions("1974-01-16T12:30")
    # BDST 1941: London 08:00 local = 06:00 UTC
    assert "London" in active_sessions("1941-06-03T06:30")
    assert "London" not in active_sessions("2024-06-04T06:30")


def test_weekend_is_local():
    # Sunday 22:30 UTC is already Monday 09:30 in Sydney: Sydney open,
    # every centre further west still on its local weekend.
    assert active_sessions("2024-01-14T22:30") == ["Sydney"]
    # Saturday midday UTC: nothing anywhere.
    assert session_name("2024-01-13T12:00") == "None"


# ===========================================================================
# 6. Requirement 2 — label a whole dataset (vectorized, cross-checked)
# ===========================================================================

def _sample_frame():
    # Spans the 2024-03-10 US spring-forward.
    idx = pd.date_range("2024-03-08", "2024-03-13", freq="30min", tz="UTC")
    return pd.DataFrame(
        {"px": np.random.default_rng(0).normal(size=len(idx))}, index=idx
    )


def test_label_sessions_matches_scalar_api():
    df = _sample_frame()
    lab = label_sessions(df)
    mismatches = [t for t in df.index if session_name(t) != lab.loc[t, "session"]]
    assert not mismatches, f"{len(mismatches)} vector/scalar mismatches, first: {mismatches[0]}"
    assert all(f"sess_{s.name}" in lab.columns for s in DEFAULT_SESSIONS)


def test_label_sessions_tracks_dst_shift():
    lab = label_sessions(_sample_frame())
    # NY open moved from 13:00 UTC (Fri Mar 8, EST) to 12:00 UTC (Mon Mar 11, EDT)
    assert bool(lab.loc["2024-03-08 13:00+00:00", "sess_NewYork"]) is True
    assert bool(lab.loc["2024-03-08 12:30+00:00", "sess_NewYork"]) is False
    assert bool(lab.loc["2024-03-11 12:30+00:00", "sess_NewYork"]) is True
    assert int(lab["session_count"].max()) >= 4          # EU/UK/US overlap
    assert lab.loc["2024-03-09 12:00+00:00", "session"] == "None"  # Saturday


def test_label_sessions_input_variants():
    df = _sample_frame()
    lab = label_sessions(df)
    # naive index assumed UTC
    lab_naive = label_sessions(df.tz_localize(None))
    assert (lab_naive["session"].values == lab["session"].values).all()
    # timestamps in a column instead of the index
    df_col = df.reset_index().rename(columns={"index": "ts"})
    lab_col = label_sessions(df_col, ts_col="ts")
    assert (lab_col["session"].values == lab["session"].values).all()


# ===========================================================================
# 7. Requirements 3 & 4 — naive/aware handling, UTC <-> local conversion
# ===========================================================================

def test_make_naive():
    aware = pd.Timestamp("2024-03-10T06:59", tz="UTC")
    assert make_naive(aware) == pd.Timestamp("2024-03-10T06:59")
    ny_local = aware.tz_convert("America/New_York")       # 01:59 EST
    assert make_naive(ny_local, keep_wall_clock=True) == pd.Timestamp("2024-03-10T01:59")
    assert make_naive(pd.Series([aware])).iloc[0] == pd.Timestamp("2024-03-10T06:59")
    # already-naive input passes through unchanged
    assert make_naive(pd.Timestamp("2024-01-01")) == pd.Timestamp("2024-01-01")


def test_utc_local_conversions():
    assert str(utc_to_local("2024-01-15T07:00", "America/New_York")) == \
        "2024-01-15 02:00:00-05:00"
    # round trip UTC -> Tokyo wall clock -> UTC
    wall = make_naive(utc_to_local("2024-06-15T07:00", "Asia/Tokyo"),
                      keep_wall_clock=True)
    assert local_to_utc(wall, "Asia/Tokyo") == ensure_utc("2024-06-15T07:00")


def test_ambiguous_and_nonexistent_local_times():
    # 2024-11-03 01:30 New York happens twice (fall back)
    assert str(local_to_utc("2024-11-03T01:30", "America/New_York",
                            ambiguous="earliest")) == "2024-11-03 05:30:00+00:00"  # EDT
    assert str(local_to_utc("2024-11-03T01:30", "America/New_York",
                            ambiguous="latest")) == "2024-11-03 06:30:00+00:00"    # EST
    # 2024-03-10 02:30 New York never happens (spring forward): shifted forward
    assert str(local_to_utc("2024-03-10T02:30", "America/New_York")) == \
        "2024-03-10 07:00:00+00:00"


# ===========================================================================
# 8. Requirements 5, 6 & 7 — calendar, DST introspection, market state
# ===========================================================================

def test_day_of_week_and_month():
    assert day_of_week("2026-07-09") == "Thursday"
    assert day_of_week("2026-07-09", as_name=False) == 3
    # Fri 23:00 UTC is already Saturday in Sydney
    assert day_of_week("2024-01-12T23:00", tz="Australia/Sydney") == "Saturday"
    assert month_of_year("2026-07-09") == "July"
    assert month_of_year("2026-07-09", as_name=False) == 7
    s = pd.Series(pd.to_datetime(["2024-01-01", "2024-06-01"]))
    assert list(day_of_week(s)) == ["Monday", "Saturday"]
    assert list(month_of_year(s, as_name=False)) == [1, 6]


def test_add_calendar_columns():
    cal = add_calendar_columns(_sample_frame().head(3))
    assert {"dow", "dow_name", "month", "month_name", "hour_utc", "date"} <= set(cal.columns)
    assert cal["dow_name"].iloc[0] == "Friday"            # 2024-03-08


def test_dst_introspection():
    assert is_dst("2024-07-01T12:00", "America/New_York") is True
    assert is_dst("1974-01-15T12:00", "America/New_York") is True   # emergency era
    tr74 = dst_transitions("America/New_York", 1974)
    assert str(tr74[0][0].date()) == "1974-01-06"
    trs = dst_transitions("Asia/Singapore", 1981)
    assert (trs[-1][1], trs[-1][2]) == (7.5, 8.0)          # +7:30 -> +8 base move


def test_fx_market_is_open():
    assert fx_market_is_open("2024-01-10T12:00") is True             # Wed midday
    assert fx_market_is_open("2024-01-12T22:30") is False            # Fri 17:30 NY (winter)
    assert fx_market_is_open("2024-01-13T12:00") is False            # Saturday
    assert fx_market_is_open("2024-01-14T22:30") is True             # Sun 17:30 NY (winter)
    assert fx_market_is_open("2024-07-12T21:30") is False            # Fri 17:30 NY (summer)


# ===========================================================================
# Standalone fallback: `python test_market_sessions.py` (no pytest needed).
# Kept inside __main__ so pytest's import-time collection never executes it.
# ===========================================================================

if __name__ == "__main__":
    import sys
    import traceback

    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  [PASS] {name}")
        except AssertionError as exc:
            failed += 1
            print(f"  [FAIL] {name}: {exc}")
        except Exception:
            failed += 1
            print(f"  [FAIL] {name}: unexpected error")
            traceback.print_exc()
    print(f"\nRESULT: {len(tests) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)