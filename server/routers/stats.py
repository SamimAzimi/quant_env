"""Market-data stats endpoints: yesterday charts, key levels, log returns."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from .. import marketdata

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/assets")
def assets():
    """Assets available in the CSV store plus the default chart list."""
    return {
        "available": marketdata.available_assets(),
        "default_charts": marketdata.CHART_ASSETS,
        "timeframes": marketdata.TIMEFRAMES,
    }


@router.get("/charts")
def charts(tf: str = Query("15m"), assets: str | None = Query(None)):
    """Yesterday's bars + key levels per asset (comma-separated tickers)."""
    if tf not in marketdata.TIMEFRAMES:
        raise HTTPException(422, f"Unknown timeframe {tf!r}")
    names = ([a.strip() for a in assets.split(",") if a.strip()]
             if assets else marketdata.CHART_ASSETS)
    out, errors = [], {}
    for asset in names:
        try:
            out.append(marketdata.yesterday_chart(asset, tf))
        except (FileNotFoundError, ValueError) as e:
            errors[asset] = str(e)
    return {"charts": out, "errors": errors}


@router.get("/returns")
def returns(tf: str = Query("15m"), assets: str | None = Query(None)):
    """Cumulative log returns (%) across yesterday for the selected assets."""
    if tf not in marketdata.TIMEFRAMES:
        raise HTTPException(422, f"Unknown timeframe {tf!r}")
    names = ([a.strip() for a in assets.split(",") if a.strip()]
             if assets else marketdata.CHART_ASSETS)
    return marketdata.yesterday_log_returns(names, tf)
