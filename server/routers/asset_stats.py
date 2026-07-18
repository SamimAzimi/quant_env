"""Asset behaviour statistics endpoint (session/overlap, σ-bands, matrix).

The engine is pure NumPy/pandas over the CSV store and can be heavy on long
histories, so results are cached per (asset, timeframe, range, file mtime).
"""
from __future__ import annotations

import os
from datetime import date
from functools import lru_cache

from fastapi import APIRouter, HTTPException, Query

from .. import asset_stats
from ..utils import guard_csv

router = APIRouter(prefix="/api/asset-stats", tags=["asset-stats"])


_guard = guard_csv          # shared implementation (server/utils.py)


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


@lru_cache(maxsize=8)
def _cached_bands(asset: str, tf: str, start: str, end: str, mtime: float) -> dict:
    from .. import band_behavior
    s = date.fromisoformat(start) if start else None
    e = date.fromisoformat(end) if end else None
    return band_behavior.analyze_bands(asset, tf, s, e)


@router.get("/bands")
def band_study(asset: str = Query(...), tf: str = Query("15m"),
               start: str = Query(""), end: str = Query("")):
    """Band-behaviour study (A–G) for each consecutive session pair."""
    path = _guard(asset, tf)
    try:
        return _cached_bands(asset, tf, start, end, os.path.getmtime(path))
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(404, str(e))


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
