"""Small helpers shared across the server package.

Each function here replaced several identical per-module copies — the
behaviour is exactly the code that used to be duplicated.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import HTTPException

from . import marketdata


def naive_utc(dt: datetime | None) -> datetime | None:
    """Store naive UTC; tz-aware inputs are converted, naive assumed UTC."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.replace(tzinfo=None)


def guard_csv(asset: str, tf: str) -> str:
    """Validate a stats request's timeframe + CSV presence; return the path."""
    if tf not in marketdata.TIMEFRAMES:
        raise HTTPException(422, f"Unknown timeframe {tf!r}; choose one of "
                                 f"{marketdata.TIMEFRAMES}")
    path = marketdata.csv_path(asset, tf)
    if not os.path.exists(path):
        raise HTTPException(404, f"No {tf} data for {asset}. Run "
                                 f"libs/data_manager.py to download it.")
    return path
