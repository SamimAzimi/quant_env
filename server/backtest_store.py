"""MySQL-backed backtest store — the app-database twin of libs/result_store.

Persists everything ResultStore.save_pipeline saves, normalized into the
Market-Prep database (MARKET_PREP_DB_URL):

    bt_runs      one row per run (identity + metadata JSON)
    bt_metrics   scalar KPIs, key/value (numeric + text fallback)
    bt_trades    the account ledger, typed columns + strategy extras as JSON
    bt_equity    the equity curve points
    bt_frames    report breakdowns (exit_reasons, monthly_returns, rolling_*,
                 by_*), the costed table, and strategy detail frames — each
                 stored as a pandas-split JSON payload

Interface-compatible with ResultStore where the pipeline touches it:
``save_pipeline(...)`` and ``summary_table()``.
"""
from __future__ import annotations

import json
import math
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd

from .db import Base, SessionLocal, engine
from .models import BtEquityPoint, BtFrame, BtMetric, BtRun, BtTrade

HEADLINE_KEYS = ["net_profit", "win_rate", "profit_factor", "sharpe", "sortino",
                 "max_drawdown_pct", "total_return_pct", "final_equity",
                 "expectancy_r"]

_TRADE_COLS = {
    "trade_id", "side", "setup_time", "entry_time", "exit_time",
    "entry_price", "exit_price", "sl_price", "tp_price", "exit_reason",
    "lots", "units", "notional", "spread_cost", "commission_cost",
    "financing_cost", "total_cost", "gross_pnl", "net_pnl", "r_multiple",
    "equity_after",
}
_TIME_COLS = ("setup_time", "entry_time", "exit_time")
_STR_COLS = ("trade_id", "side", "exit_reason")


def _clean(v):
    """SQL-safe scalar: NaN/NaT → None, numpy → python."""
    if v is None:
        return None
    if isinstance(v, (np.floating, np.integer)):
        v = v.item()
    if isinstance(v, float) and not math.isfinite(v):
        return None
    if v is pd.NaT or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v


def _to_dt(v):
    v = _clean(v)
    if v is None:
        return None
    ts = pd.Timestamp(v)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return ts.to_pydatetime()


def _frame_payload(obj) -> str:
    """DataFrame/Series → JSON string (pandas 'split', ISO dates)."""
    if isinstance(obj, pd.Series):
        obj = obj.to_frame(name=obj.name or "value")
    df = obj.reset_index() if not isinstance(obj.index, pd.RangeIndex) else obj
    return df.to_json(orient="split", date_format="iso")


class BacktestStore:
    """Save/read pipeline runs in the Market-Prep database."""

    def __init__(self, db_file: Optional[str] = None):   # db_file kept for
        del db_file                                       # signature parity
        Base.metadata.create_all(engine)

    # ── save ──────────────────────────────────────────────────────────────────

    def save_pipeline(self, run_id: str, asset: str, *,
                      backtest: Optional[Tuple[pd.DataFrame, Dict]] = None,
                      account: Optional[Tuple[pd.DataFrame, pd.DataFrame]] = None,
                      performance: Optional[Any] = None,
                      costed: Optional[pd.DataFrame] = None,
                      extra_metadata: Optional[Dict] = None,
                      overwrite: bool = True) -> str:
        details = backtest[1] if backtest is not None else {}
        result_df = account[0] if account is not None else None
        equity_curve = account[1] if account is not None else None
        report = (performance.report() if hasattr(performance, "report")
                  else performance) or {}
        metrics = report.get("metrics", {}) if isinstance(report, dict) else {}
        meta = dict(details.get("metadata") or {})
        meta.update(extra_metadata or {})

        with SessionLocal() as db:
            existing = db.query(BtRun).filter(BtRun.run_id == run_id).first()
            if existing:
                if not overwrite:
                    raise ValueError(f"run_id {run_id!r} already stored")
                db.delete(existing)
                db.flush()

            run = BtRun(
                run_id=run_id, asset=asset,
                strategy=str(meta.get("strategy", "")),
                timeframe=str(meta.get("timeframe", "")),
                asset_class=str(meta.get("asset_class", "")),
                n_trades=int(result_df["net_pnl"].notna().sum())
                if result_df is not None and "net_pnl" in result_df else 0,
                metadata_json=json.dumps(meta, default=str),
            )
            db.add(run)
            db.flush()

            for name, value in (metrics or {}).items():
                v = _clean(value)
                if isinstance(v, bool):
                    db.add(BtMetric(run_pk=run.id, name=name, text_value=str(v)))
                elif isinstance(v, (int, float)):
                    db.add(BtMetric(run_pk=run.id, name=name, value=float(v)))
                else:
                    db.add(BtMetric(run_pk=run.id, name=name,
                                    text_value=None if v is None else str(v)[:120]))

            if result_df is not None:
                for row in result_df.to_dict("records"):
                    extra = {k: _clean(v) for k, v in row.items()
                             if k not in _TRADE_COLS}
                    kw = {}
                    for col in _TRADE_COLS:
                        if col not in row:
                            continue
                        if col in _TIME_COLS:
                            kw[col] = _to_dt(row[col])
                        elif col in _STR_COLS:
                            v = _clean(row[col])
                            kw[col] = None if v is None else str(v)
                        else:
                            v = _clean(row[col])
                            kw[col] = None if v is None else float(v)
                    db.add(BtTrade(run_pk=run.id, extra_json=json.dumps(extra, default=str), **kw))

            if equity_curve is not None:
                for row in equity_curve.to_dict("records"):
                    db.add(BtEquityPoint(
                        run_pk=run.id,
                        step=int(_clean(row.get("step")) or 0),
                        time=_to_dt(row.get("time")),
                        trade_id=str(_clean(row.get("trade_id")) or "") or None,
                        equity=float(_clean(row.get("equity")) or 0.0),
                    ))

            frames: Dict[str, Any] = {}
            if isinstance(report, dict):
                for k, v in report.items():
                    if k in ("metrics", "equity_curve"):
                        continue
                    if isinstance(v, (pd.DataFrame, pd.Series)):
                        frames[k] = v
            if costed is not None:
                frames["costed"] = costed
            for k, v in (details or {}).items():
                if k != "trades" and isinstance(v, (pd.DataFrame, pd.Series)):
                    frames[f"details:{k}"] = v
            for name, obj in frames.items():
                db.add(BtFrame(run_pk=run.id, name=name[:80],
                               payload=_frame_payload(obj)))

            db.commit()
        return run_id

    # ── read (parity with ResultStore.summary_table) ─────────────────────────

    def summary_table(self, asset: Optional[str] = None) -> pd.DataFrame:
        with SessionLocal() as db:
            q = db.query(BtRun)
            if asset is not None:
                q = q.filter(BtRun.asset == asset)
            rows = []
            for run in q.order_by(BtRun.saved_at.asc()).all():
                m = {x.name: (x.value if x.value is not None else x.text_value)
                     for x in run.metrics}
                rows.append({"run_id": run.run_id, "asset": run.asset,
                             "saved_at": run.saved_at.isoformat(),
                             **{k: m.get(k) for k in HEADLINE_KEYS}})
        return pd.DataFrame(rows)
