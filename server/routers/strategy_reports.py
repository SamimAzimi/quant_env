"""Strategy reports: browse backtest runs persisted by the pipeline.

The report endpoint carries everything the old ResultStore dashboard
showed: headline KPIs, composite score + rank, grouped metric panels
(config.dashboard_meta), equity curve, breakdown frames, long-vs-short
split, a Monte Carlo bootstrap of trade returns, and the cost summary.
"""
from __future__ import annotations

import json
import math

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from config.dashboard_meta import METRIC_GROUPS, METRIC_META, SCORE_TERMS
from ..backtest_store import HEADLINE_KEYS
from ..db import get_db
from ..models import BtEquityPoint, BtFrame, BtMetric, BtRun, BtTrade

router = APIRouter(prefix="/api/strategy-reports", tags=["strategy-reports"])


def _metrics_dict(run: BtRun) -> dict:
    return {m.name: (m.value if m.value is not None else m.text_value)
            for m in run.metrics}


def _composite_score(metrics: dict) -> float | None:
    """Weighted score over the headline metrics (config SCORE_TERMS)."""
    s, used = 0.0, False
    for col, w, scale in SCORE_TERMS:
        v = metrics.get(col)
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(v):
            s += w * v * scale
            used = True
    return round(s, 4) if used else None


def _all_scores(db: Session) -> dict[str, float]:
    return {r.run_id: sc for r in db.query(BtRun).all()
            if (sc := _composite_score(_metrics_dict(r))) is not None}


def _rank(scores: dict[str, float], run_id: str) -> int | None:
    if run_id not in scores:
        return None
    mine = scores[run_id]
    return 1 + sum(1 for s in scores.values() if s > mine)


def _metric_groups(metrics: dict) -> list[dict]:
    """The dashboard's grouped panels: [{name, items:[{key,label,kind,value}]}]."""
    def item(k):
        label, kind = METRIC_META.get(k, (k.replace("_", " "), "num"))
        return {"key": k, "label": label, "kind": kind, "value": metrics[k]}

    out, shown = [], set()
    for gname, keys in METRIC_GROUPS.items():
        present = [k for k in keys if k in metrics and metrics[k] is not None]
        if present:
            out.append({"name": gname, "items": [item(k) for k in present]})
            shown.update(present)
    others = [k for k in metrics if k not in shown and metrics[k] is not None]
    if others:
        out.append({"name": "Other metrics", "items": [item(k) for k in others]})
    return out


def _filled(trades: list[BtTrade]) -> list[BtTrade]:
    return [t for t in trades if t.net_pnl is not None]


def _long_short(trades: list[BtTrade]) -> list[dict]:
    rows = []
    for side in ("long", "short"):
        s = [t for t in _filled(trades) if t.side == side]
        if not s:
            continue
        wins = sum(1 for t in s if t.net_pnl > 0)
        net = sum(t.net_pnl for t in s)
        rows.append({"side": side, "trades": len(s), "wins": wins,
                     "win_rate_pct": round(100 * wins / len(s), 1),
                     "net_pnl": round(net, 2),
                     "avg_pnl": round(net / len(s), 2)})
    return rows


def _cost_summary(trades: list[BtTrade]) -> dict:
    f = _filled(trades)
    out = {"trades": len(f)}
    for col in ("spread_cost", "commission_cost", "financing_cost",
                "total_cost", "gross_pnl", "net_pnl"):
        vals = [getattr(t, col) for t in f if getattr(t, col) is not None]
        out[col] = round(float(sum(vals)), 2) if vals else None
    return out


def _monte_carlo(trades: list[BtTrade], initial: float | None,
                 n_paths: int = 1000, seed: int = 0) -> dict | None:
    """Bootstrap of per-trade fractional returns (dashboard parity)."""
    rets = []
    for t in _filled(trades):
        base = (t.equity_after - t.net_pnl) if t.equity_after is not None else initial
        if base:
            rets.append(t.net_pnl / float(base))
    r = np.asarray(rets, float)
    r = r[np.isfinite(r)]
    if len(r) < 5:
        return None
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(r), size=(n_paths, len(r)))
    paths = np.cumprod(1.0 + r[idx], axis=1)
    terminal = (paths[:, -1] - 1.0) * 100.0
    runmax = np.maximum.accumulate(paths, axis=1)
    maxdd = (1.0 - paths / runmax).max(axis=1) * 100.0
    counts, edges = np.histogram(terminal, bins=30)
    return {
        "n_paths": n_paths, "n_trades": int(len(r)),
        "median_return": round(float(np.median(terminal)), 2),
        "p10_return": round(float(np.percentile(terminal, 10)), 2),
        "p90_return": round(float(np.percentile(terminal, 90)), 2),
        "prob_profit": round(float((terminal > 0).mean() * 100), 1),
        "median_maxdd": round(float(np.median(maxdd)), 2),
        "p90_maxdd": round(float(np.percentile(maxdd, 90)), 2),
        "worst_maxdd": round(float(maxdd.max()), 2),
        "hist": {"edges": [round(float(e), 2) for e in edges],
                 "counts": [int(c) for c in counts]},
    }


@router.get("")
def list_runs(db: Session = Depends(get_db)):
    """All stored runs, newest first, with headline metrics + score/rank."""
    runs = db.query(BtRun).order_by(BtRun.saved_at.desc()).all()
    scores = {}
    metric_cache = {}
    for run in runs:
        m = metric_cache[run.run_id] = _metrics_dict(run)
        sc = _composite_score(m)
        if sc is not None:
            scores[run.run_id] = sc
    out = []
    for run in runs:
        m = metric_cache[run.run_id]
        out.append({
            "run_id": run.run_id, "asset": run.asset, "strategy": run.strategy,
            "timeframe": run.timeframe, "asset_class": run.asset_class,
            "saved_at": run.saved_at.isoformat(), "n_trades": run.n_trades,
            "composite_score": scores.get(run.run_id),
            "rank": _rank(scores, run.run_id),
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
    """Full report: metadata, metrics (+groups/score/rank), equity curve,
    breakdown frames, long-vs-short, Monte Carlo, cost summary."""
    run = _get_run(db, run_id)
    metrics = _metrics_dict(run)
    metadata = json.loads(run.metadata_json or "{}")
    equity = (db.query(BtEquityPoint).filter(BtEquityPoint.run_pk == run.id)
              .order_by(BtEquityPoint.step.asc()).all())
    frames = {f.name: json.loads(f.payload)
              for f in db.query(BtFrame).filter(BtFrame.run_pk == run.id).all()}
    trades = db.query(BtTrade).filter(BtTrade.run_pk == run.id).all()
    try:
        initial = float(metadata.get("initial_capital"))
    except (TypeError, ValueError):
        initial = equity[0].equity if equity else None
    scores = _all_scores(db)
    return {
        "run_id": run.run_id, "asset": run.asset, "strategy": run.strategy,
        "timeframe": run.timeframe, "asset_class": run.asset_class,
        "saved_at": run.saved_at.isoformat(), "n_trades": run.n_trades,
        "metadata": metadata,
        "metrics": metrics,
        "metric_groups": _metric_groups(metrics),
        "composite_score": scores.get(run.run_id),
        "rank": _rank(scores, run.run_id),
        "n_runs": len(scores),
        "equity": [{"step": p.step,
                    "time": p.time.isoformat() if p.time else None,
                    "equity": p.equity} for p in equity],
        "frames": frames,
        "long_short": _long_short(trades),
        "monte_carlo": _monte_carlo(trades, initial),
        "cost_summary": _cost_summary(trades),
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


@router.delete("", status_code=204)
def delete_all_runs(db: Session = Depends(get_db)):
    """Wipe every stored run and all its dependent rows (metrics, trades,
    equity points, frames) — children first, so nothing is left behind."""
    for model in (BtMetric, BtTrade, BtEquityPoint, BtFrame):
        db.query(model).delete(synchronize_session=False)
    db.query(BtRun).delete(synchronize_session=False)
    db.commit()


@router.delete("/{run_id}", status_code=204)
def delete_run(run_id: str, db: Session = Depends(get_db)):
    """Delete one run; ORM cascades remove its metrics/trades/equity/frames."""
    db.delete(_get_run(db, run_id))
    db.commit()
