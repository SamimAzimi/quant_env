"""Tests for libs.indicators — pure technical helpers."""
import numpy as np
import pandas as pd
import pytest

from libs import indicators as ind


# ── ATR ──────────────────────────────────────────────────────────────────────

def test_atr_length_one_equals_true_range():
    # alpha = 1/length = 1 → the EWM collapses to the raw true range
    df = pd.DataFrame({
        "High":  [10.0, 12.0, 11.0],
        "Low":   [ 9.0, 10.5, 10.0],
        "Close": [ 9.5, 11.5, 10.2],
    })
    atr = ind.calculate_atr(df, length=1)
    # bar0: H-L = 1.0 (no previous close)
    # bar1: max(1.5, |12-9.5|=2.5, |10.5-9.5|=1.0) = 2.5
    # bar2: max(1.0, |11-11.5|=0.5, |10-11.5|=1.5) = 1.5
    assert atr.tolist() == pytest.approx([1.0, 2.5, 1.5])


def test_atr_constant_price_is_zero():
    df = pd.DataFrame({"High": [5.0] * 10, "Low": [5.0] * 10, "Close": [5.0] * 10})
    assert ind.calculate_atr(df, length=3).tolist() == pytest.approx([0.0] * 10)


# ── fractals ─────────────────────────────────────────────────────────────────

@pytest.fixture
def swing_df():
    return pd.DataFrame({
        "High": [1.0, 2.0, 5.0, 2.0, 1.0],
        "Low":  [0.5, 0.2, 0.1, 0.3, 0.6],
    })


def test_fractal_high_detected_at_peak(swing_df):
    assert ind.is_fractal_high(swing_df, 2, fractal_left=2, fractal_right=2)
    assert not ind.is_fractal_high(swing_df, 1, fractal_left=1, fractal_right=1)


def test_fractal_low_detected_at_trough(swing_df):
    assert ind.is_fractal_low(swing_df, 2, fractal_left=2, fractal_right=2)
    assert not ind.is_fractal_low(swing_df, 3, fractal_left=1, fractal_right=1)


def test_fractal_out_of_bounds_is_false(swing_df):
    assert not ind.is_fractal_high(swing_df, 0, fractal_left=2, fractal_right=2)
    assert not ind.is_fractal_high(swing_df, 4, fractal_left=2, fractal_right=2)


# ── rejection candle ─────────────────────────────────────────────────────────

def test_bullish_pin_bar_detected():
    # long lower wick, small upper wick, bullish close
    df = pd.DataFrame({"Open": [10.0], "High": [10.6], "Low": [7.0], "Close": [10.5]})
    assert ind.is_rejection_candle(df, 0, "bullish", True, wick_ratio=2.0, body_ratio=1.0)


def test_bearish_body_fails_bullish_rejection():
    df = pd.DataFrame({"Open": [10.5], "High": [10.6], "Low": [7.0], "Close": [10.0]})
    assert not ind.is_rejection_candle(df, 0, "bullish", True, wick_ratio=2.0, body_ratio=1.0)


def test_rejection_disabled_always_passes():
    df = pd.DataFrame({"Open": [1.0], "High": [1.0], "Low": [1.0], "Close": [1.0]})
    assert ind.is_rejection_candle(df, 0, "bullish", False, wick_ratio=2.0, body_ratio=1.0)


# ── sessions ─────────────────────────────────────────────────────────────────

def _bar_at(hour, weekday_date="2024-01-01"):   # 2024-01-01 is a Monday
    return pd.DataFrame({"Datetime": [pd.Timestamp(f"{weekday_date} {hour:02d}:00")]})


def test_in_session_plain_window():
    assert ind.in_session(_bar_at(9), 0, True, 7, 16, session_days=[0, 1, 2, 3, 4])
    assert not ind.in_session(_bar_at(20), 0, True, 7, 16, session_days=[0, 1, 2, 3, 4])


def test_in_session_wraps_midnight():
    assert ind.in_session(_bar_at(23), 0, True, 21, 6, session_days=[0, 1, 2, 3, 4])
    assert ind.in_session(_bar_at(3), 0, True, 21, 6, session_days=[0, 1, 2, 3, 4])
    assert not ind.in_session(_bar_at(12), 0, True, 21, 6, session_days=[0, 1, 2, 3, 4])


def test_in_session_rejects_wrong_weekday():
    saturday = _bar_at(9, "2024-01-06")
    assert not ind.in_session(saturday, 0, True, 7, 16, session_days=[0, 1, 2, 3, 4])


def test_get_session_name_buckets():
    assert ind.get_session_name(_bar_at(3), 0) == "asian"
    assert ind.get_session_name(_bar_at(8), 0) == "london"
    assert ind.get_session_name(_bar_at(13), 0) == "new_york_overlap"
    assert ind.get_session_name(_bar_at(18), 0) == "new_york"
    assert ind.get_session_name(_bar_at(22), 0) == "off_hours"


# ── MAE / MFE ────────────────────────────────────────────────────────────────

def test_update_mae_mfe_long():
    mae, mfe = ind.update_mae_mfe("bullish", bar_low=95.0, bar_high=105.0,
                                  current_mae=98.0, current_mfe=102.0)
    assert (mae, mfe) == (95.0, 105.0)


def test_update_mae_mfe_short():
    mae, mfe = ind.update_mae_mfe("bearish", bar_low=95.0, bar_high=105.0,
                                  current_mae=102.0, current_mfe=98.0)
    assert (mae, mfe) == (105.0, 95.0)


# ── volume profile ───────────────────────────────────────────────────────────

def test_volume_profile_poc_at_high_volume_price():
    rng = np.random.default_rng(1)
    n = 200
    close = np.full(n, 100.0)
    close[50:60] = 110.0                       # a second traded level
    volume = np.full(n, 10.0)
    volume[50:60] = 1000.0                     # …with dominant volume
    df = pd.DataFrame({
        "High": close + 0.5, "Low": close - 0.5, "Close": close,
        "Volume": volume,
    })
    poc, vah, val = ind.calculate_volume_profile(df, 0, n - 1)
    assert poc == pytest.approx(110.0, abs=1.0)
    assert df["Low"].min() <= val <= vah <= df["High"].max()


def test_volume_profile_without_volume_returns_none():
    df = pd.DataFrame({"High": [1.0, 2.0], "Low": [0.5, 1.0], "Close": [0.9, 1.5]})
    assert ind.calculate_volume_profile(df, 0, 1) == (None, None, None)
