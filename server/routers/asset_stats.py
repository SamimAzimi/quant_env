"""Asset behaviour statistics endpoint (session/overlap, σ-bands, matrix).

The engine is pure NumPy/pandas over the CSV store and can be heavy on long
histories, so results are cached per (asset, timeframe, range, file mtime).
"""
from __future__ import annotations

import os
from datetime import date
from functools import lru_cache

from fastapi import APIRouter, HTTPException, Query

from .. import asset_stats, marketdata

router = APIRouter(prefix="/api/asset-stats", tags=["asset-stats"])


def _csv_path(asset: str, tf: str) -> str:
    return os.path.join(str(marketdata.MARKET_DATA_DIR), asset, f"{tf}.csv")


def _guard(asset: str, tf: str) -> str:
    if tf not in marketdata.TIMEFRAMES:
        raise HTTPException(422, f"Unknown timeframe {tf!r}; choose one of "
                                 f"{marketdata.TIMEFRAMES}")
    path = _csv_path(asset, tf)
    if not os.path.exists(path):
        raise HTTPException(404, f"No {tf} data for {asset}. Run "
                                 f"libs/data_manager.py to download it.")
    return path


@router.get("/range")
def data_range(asset: str = Query(...), tf: str = Query("15m")):
    """Available date range for an asset+timeframe (populates the pickers)."""
    _guard(asset, tf)
    try:
        return asset_stats.available_range(asset, tf)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(404, str(e))


@lru_cache(maxsize=16)
def _cached(asset: str, tf: str, start: str, end: str, mtime: float) -> dict:
    s = date.fromisoformat(start) if start else None
    e = date.fromisoformat(end) if end else None
    return asset_stats.analyze(asset, tf, s, e)


@router.get("")
def asset_statistics(asset: str = Query(...), tf: str = Query("15m"),
                     start: str = Query(""), end: str = Query("")):
    """Full behaviour report. Timeframe must be intraday; date range defaults
    to all available history when start/end are omitted."""
    path = _guard(asset, tf)
    try:
        return _cached(asset, tf, start, end, os.path.getmtime(path))
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(404, str(e))
