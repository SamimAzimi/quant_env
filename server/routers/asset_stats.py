"""Asset behaviour statistics endpoint (session transitions + day-over-day).

The engine is pure NumPy/pandas over the CSV store and can be heavy on
long histories, so results are cached per (asset, timeframe, file mtime).
"""
from __future__ import annotations

import os
from functools import lru_cache

from fastapi import APIRouter, HTTPException, Query

from .. import asset_stats, marketdata

router = APIRouter(prefix="/api/asset-stats", tags=["asset-stats"])


@lru_cache(maxsize=32)
def _cached(asset: str, tf: str, mtime: float) -> dict:
    return asset_stats.analyze(asset, tf)


@router.get("")
def asset_statistics(asset: str = Query(...), tf: str = Query("15m")):
    """Full behaviour report. Timeframe must be intraday (< 1 day)."""
    if tf not in marketdata.TIMEFRAMES:
        raise HTTPException(422, f"Unknown timeframe {tf!r}; choose one of "
                                 f"{marketdata.TIMEFRAMES}")
    path = os.path.join(str(marketdata.MARKET_DATA_DIR), asset, f"{tf}.csv")
    if not os.path.exists(path):
        raise HTTPException(404, f"No {tf} data for {asset}. Run "
                                 f"libs/data_manager.py to download it.")
    try:
        return _cached(asset, tf, os.path.getmtime(path))
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(404, str(e))
