"""Strategy reports: browse backtest runs persisted by the pipeline."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..backtest_store import HEADLINE_KEYS
from ..db import get_db
from ..models import BtEquityPoint, BtFrame, BtRun, BtTrade

router = APIRouter(prefix="/api/strategy-reports", tags=["strategy-reports"])


def _metrics_dict(run: BtRun) -> dict:
    return {m.name: (m.value if m.value is not None else m.text_value)
            for m in run.metrics}


@router.get("")
def list_runs(db: Session = Depends(get_db)):
    """All stored runs, newest first, with headline metrics."""
    out = []
    for run in db.query(BtRun).order_by(BtRun.saved_at.desc()).all():
        m = _metrics_dict(run)
        out.append({
            "run_id": run.run_id, "asset": run.asset, "strategy": run.strategy,
            "timeframe": run.timeframe, "asset_class": run.asset_class,
            "saved_at": run.saved_at.isoformat(), "n_trades": run.n_trades,
            "headline": {k: m.get(k) for k in HEADLINE_KEYS},
        })
    return out


def _get_run(db: Session, run_id: str) -> BtRun:
    run = db.query(BtRun).filter(BtRun.run_id == run_id).first()
    if not run:
        raise HTTPException(404, f"No stored run {run_id!r}")
    return run


@router.get("/{run_id}")
def run_report(run_id: str, db: Session = Depends(get_db)):
    """Full report: metadata, all metrics, equity curve, breakdown frames."""
    run = _get_run(db, run_id)
    equity = (db.query(BtEquityPoint).filter(BtEquityPoint.run_pk == run.id)
              .order_by(BtEquityPoint.step.asc()).all())
    frames = {f.name: json.loads(f.payload)
              for f in db.query(BtFrame).filter(BtFrame.run_pk == run.id).all()}
    return {
        "run_id": run.run_id, "asset": run.asset, "strategy": run.strategy,
        "timeframe": run.timeframe, "asset_class": run.asset_class,
        "saved_at": run.saved_at.isoformat(), "n_trades": run.n_trades,
        "metadata": json.loads(run.metadata_json or "{}"),
        "metrics": _metrics_dict(run),
        "equity": [{"step": p.step,
                    "time": p.time.isoformat() if p.time else None,
                    "equity": p.equity} for p in equity],
        "frames": frames,
    }


@router.get("/{run_id}/trades")
def run_trades(run_id: str, limit: int = Query(100, le=1000), offset: int = 0,
               db: Session = Depends(get_db)):
    run = _get_run(db, run_id)
    q = (db.query(BtTrade).filter(BtTrade.run_pk == run.id)
         .order_by(BtTrade.id.asc()))
    total = q.count()
    rows = []
    for t in q.offset(offset).limit(limit).all():
        rows.append({
            "trade_id": t.trade_id, "side": t.side,
            "entry_time": t.entry_time.isoformat() if t.entry_time else None,
            "exit_time": t.exit_time.isoformat() if t.exit_time else None,
            "entry_price": t.entry_price, "exit_price": t.exit_price,
            "sl_price": t.sl_price, "tp_price": t.tp_price,
            "exit_reason": t.exit_reason, "net_pnl": t.net_pnl,
            "gross_pnl": t.gross_pnl, "total_cost": t.total_cost,
            "r_multiple": t.r_multiple, "equity_after": t.equity_after,
            "extra": json.loads(t.extra_json or "{}"),
        })
    return {"total": total, "offset": offset, "rows": rows}


@router.delete("/{run_id}", status_code=204)
def delete_run(run_id: str, db: Session = Depends(get_db)):
    db.delete(_get_run(db, run_id))
    db.commit()
