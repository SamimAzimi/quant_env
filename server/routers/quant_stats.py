"""Day-over-day + quant character endpoint."""
from __future__ import annotations

import os
from datetime import date
from functools import lru_cache

from fastapi import APIRouter, HTTPException, Query

from .. import quant_stats
from ..utils import guard_csv

router = APIRouter(prefix="/api/quant-stats", tags=["quant-stats"])


_guard = guard_csv          # shared implementation (server/utils.py)


@router.get("/range")
def data_range(asset: str = Query(...), tf: str = Query("15m")):
    _guard(asset, tf)
    try:
        return quant_stats.available_range(asset, tf)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(404, str(e))


@lru_cache(maxsize=16)
def _cached(asset: str, tf: str, start: str, end: str, mtime: float) -> dict:
    s = date.fromisoformat(start) if start else None
    e = date.fromisoformat(end) if end else None
    return quant_stats.analyze(asset, tf, s, e)


@router.get("")
def quant_statistics(asset: str = Query(...), tf: str = Query("15m"),
                     start: str = Query(""), end: str = Query("")):
    path = _guard(asset, tf)
    try:
        return _cached(asset, tf, start, end, os.path.getmtime(path))
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(404, str(e))
