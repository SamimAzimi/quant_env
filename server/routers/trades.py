"""Trade journal: record trades, list today/open trades, edit later."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Trade
from ..schemas import TradeIn, TradeOut, TradePatch

router = APIRouter(prefix="/api/trades", tags=["trades"])


def _naive_utc(dt: datetime | None) -> datetime | None:
    """Store naive UTC; tz-aware inputs are converted, naive assumed UTC."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.replace(tzinfo=None)


@router.post("", response_model=TradeOut, status_code=201)
def create_trade(payload: TradeIn, db: Session = Depends(get_db)):
    trade = Trade(
        entry_time=_naive_utc(payload.entry_time),
        exit_time=_naive_utc(payload.exit_time),
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
def list_trades(db: Session = Depends(get_db)):
    """Today's trades (recorded or entered today, UTC) plus any open trade."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return (
        db.query(Trade)
        .filter(or_(
            Trade.exit_time.is_(None),
            Trade.entry_time >= start,
            Trade.created_at >= start,
        ))
        .order_by(Trade.entry_time.desc())
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
