"""Trade journal: record trades (with asset + prices), day view, history."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..dates import as_of_or_today, day_bounds, range_bounds, today_utc
from ..db import get_db
from ..utils import naive_utc
from ..models import Trade
from ..schemas import TradeIn, TradeOut, TradePatch

router = APIRouter(prefix="/api/trades", tags=["trades"])


_naive_utc = naive_utc      # shared implementation (server/utils.py)


@router.post("", response_model=TradeOut, status_code=201)
def create_trade(payload: TradeIn, db: Session = Depends(get_db)):
    trade = Trade(
        asset_id=payload.asset_id,
        entry_time=_naive_utc(payload.entry_time),
        exit_time=_naive_utc(payload.exit_time),
        entry_price=payload.entry_price,
        exit_price=payload.exit_price,
        entry_reason=payload.entry_reason,
        exit_reason=payload.exit_reason,
        tp=payload.tp,
        sl=payload.sl,
        remarks=payload.remarks,
    )
    db.add(trade)
    db.commit()
    return trade


@router.get("", response_model=list[TradeOut])
def list_trades(date_: date | None = Query(None, alias="date"),
                db: Session = Depends(get_db)):
    """Trades of the selected day (entered or recorded then).

    When viewing today, still-open trades from earlier days are included
    so nothing in flight ever drops off the page.
    """
    day = as_of_or_today(date_)
    start, end = day_bounds(day)
    cond = or_(
        Trade.entry_time.between(start, end),
        Trade.created_at.between(start, end),
    )
    if day == today_utc():
        cond = or_(cond, Trade.exit_time.is_(None))
    return db.query(Trade).filter(cond).order_by(Trade.entry_time.desc()).all()


@router.get("/history", response_model=list[TradeOut])
def history(start: date | None = None, end: date | None = None,
            db: Session = Depends(get_db)):
    """All trades whose entry falls in the date range (default: last 30d)."""
    s, e = range_bounds(start, end)
    return (
        db.query(Trade)
        .filter(Trade.entry_time >= s, Trade.entry_time < e)
        .order_by(Trade.entry_time.desc())
        .limit(1000)
        .all()
    )


@router.patch("/{trade_id}", response_model=TradeOut)
def patch_trade(trade_id: int, payload: TradePatch, db: Session = Depends(get_db)):
    trade = db.get(Trade, trade_id)
    if not trade:
        raise HTTPException(404, "Trade not found")
    data = payload.model_dump(exclude_unset=True)
    for field in ("entry_time", "exit_time"):
        if field in data:
            data[field] = _naive_utc(data[field])
    for field, value in data.items():
        setattr(trade, field, value)
    db.commit()
    return trade
