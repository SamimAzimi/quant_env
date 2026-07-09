"""
result_store.py — Persist and retrieve full backtest runs.

Refactored for the project's stack: **pyarrow (Parquet)** + **sqlite3** only —
no PyTables/HDF5, no fastparquet.

One self-contained SQLite file holds MANY runs. Each DataFrame/Series is
serialised to Parquet bytes (via pyarrow) and stored as a BLOB; a `runs`
catalog table holds per-run metadata and headline metrics for fast,
SQL-queryable cross-run comparison. A run is keyed by `run_id` and tagged with
its `asset`, and it persists the entire pipeline under that one key:

    backtester  →  trades (slim), trades_full, swings, choch_events, metadata
    account     →  result (per-trade w/ costs, risk, equity), equity_curve
    performance →  metrics (scalars) + breakdown frames (exit_reasons,
                   monthly_returns, by_month/week/dow/hour/session, rolling_*)

The store is independent of the backtester; it knows nothing about strategy
logic — it just stores and indexes frames.

Layout (inside the SQLite file)
-------------------------------
  runs(run_id PK, asset, saved_at, <headline metric columns>, metadata_json, metrics_json)
  artifacts(run_id, name, kind, data BLOB)        # name = "trades", "perf::by_month", ...

Usage
-----
    from result_store import ResultStore

    store = ResultStore("all_backtests.db")

    # one call saves an entire pipeline run for one asset
    store.save_pipeline(
        run_id   = "XAUUSD_1h_fib50",
        asset    = "XAUUSD",
        backtest    = (trades_df, details),         # CHOCHFibBacktester.backtest(df)
        account     = (result_df, equity_curve),    # CFDAccountSimulator.simulate(...)
        performance = perf.report(),                # PerformanceAnalytics.report()
        extra_metadata = {"leverage": 20, "initial_capital": 10_000, "risk_per_trade": 0.01},
        overwrite   = True,
    )

    store.list_runs(asset="XAUUSD")     # → ["XAUUSD_1h_fib50", ...]
    run = store.load_run("XAUUSD_1h_fib50")   # dict of every saved artifact
    store.summary_table()               # one row per run, headline metrics (SQL-backed)
"""
from __future__ import annotations

import io
import json
import math
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd
from config.config import DEFAULT_DB
FrameLike = Union[pd.DataFrame, pd.Series]


# ─────────────────────────────────────────────────────────────────────────────
# pyarrow compatibility shim
# ─────────────────────────────────────────────────────────────────────────────
# Some environments (notably Jupyter with %autoreload, or a reloaded pandas)
# re-run pandas' pyarrow extension-type registration. The second registration of
# "pandas.period" / "pandas.interval" raises, on the first .to_parquet() call:
#     ArrowKeyError: A type extension with name pandas.period already defined
# The duplicate is harmless (the type is already registered identically), so we
# make registration idempotent — swallow ONLY the "already defined" error.
def _make_pyarrow_registration_idempotent() -> None:
    try:
        import pyarrow as pa
    except Exception:
        return  # pyarrow not importable here; nothing to patch
    reg = getattr(pa, "register_extension_type", None)
    if reg is None or getattr(reg, "_dup_safe", False):
        return  # missing or already patched

    def _safe_register(ext_type):
        try:
            return reg(ext_type)
        except Exception as exc:                      # noqa: BLE001
            if "already defined" in str(exc):
                return None                           # duplicate — ignore
            raise

    _safe_register._dup_safe = True
    pa.register_extension_type = _safe_register
    # Trigger pandas' own registration now, under the guard, so the first
    # to_parquet() call can't hit the duplicate at an awkward moment.
    try:
        import pandas.core.arrays.arrow.extension_types  # noqa: F401
    except Exception:
        pass


_make_pyarrow_registration_idempotent()


# ─────────────────────────────────────────────────────────────────────────────
# Parquet (de)serialisation — the only place pyarrow is used.
# Kept as module-level functions so the codec is a single, swappable seam.
# ─────────────────────────────────────────────────────────────────────────────

def _frame_to_bytes(frame: pd.DataFrame, compression: Optional[str]) -> bytes:
    buf = io.BytesIO()
    frame.to_parquet(buf, engine="pyarrow", compression=compression)
    return buf.getvalue()


def _bytes_to_frame(blob: bytes) -> pd.DataFrame:
    return pd.read_parquet(io.BytesIO(blob), engine="pyarrow")


def _to_blob(obj: FrameLike, compression: Optional[str]) -> Tuple[str, bytes]:
    """Serialise a DataFrame or Series to (kind, parquet-bytes)."""
    if isinstance(obj, pd.Series):
        frame = obj.to_frame(name=(obj.name if obj.name is not None else "value"))
        return "series", _frame_to_bytes(frame, compression)
    return "frame", _frame_to_bytes(obj, compression)


def _from_blob(kind: str, blob: bytes) -> FrameLike:
    df = _bytes_to_frame(blob)
    return df.iloc[:, 0] if kind == "series" else df


# ─────────────────────────────────────────────────────────────────────────────
# ResultStore
# ─────────────────────────────────────────────────────────────────────────────

class ResultStore:
    """
    Parameters
    ----------
    filepath : str
        Path to the SQLite file. Created on first use if it does not exist.
    compression : str | None
        Parquet compression for stored frames ("snappy" default, "zstd", or None).
    """

    SCHEMA_VERSION = 1

    # metrics promoted to typed SQL columns for fast querying / summary tables
    HEADLINE_KEYS = [
        "total_trades", "net_profit", "win_rate", "profit_factor",
        "sharpe", "sortino", "max_drawdown_pct", "total_return_pct",
        "final_equity", "expectancy_r",
    ]
    # core (top-level) artifacts vs. namespaced ones ("perf::*", "extra::*")
    _CORE_ARTIFACTS = ("trades", "trades_full", "swings", "choch_events",
                       "costed", "result", "equity_curve")

    def __init__(self, filepath: str=DEFAULT_DB, compression: Optional[str] = "snappy") -> None:
        self.filepath = filepath
        self.compression = compression
        parent = os.path.dirname(os.path.abspath(filepath))
        os.makedirs(parent, exist_ok=True)
        self._ensure_schema()

    # ── high-level convenience: save a whole pipeline in one call ─────────────

    def save_pipeline(
        self,
        run_id: str,
        asset: str,
        *,
        backtest: Optional[Tuple[pd.DataFrame, Dict]] = None,   # (trades_df, details)
        account: Optional[Tuple[pd.DataFrame, pd.DataFrame]] = None,  # (result_df, equity_curve)
        performance: Optional[Any] = None,   # report dict, or a PerformanceAnalytics instance
        costed: Optional[pd.DataFrame] = None,   # CFDCostModel.add_costs(trades_df)
        extra_metadata: Optional[Dict] = None,
        extra_tables: Optional[Dict[str, FrameLike]] = None,
        overwrite: bool = False,
    ) -> str:
        """Unpack the pipeline objects and persist them under one run/asset."""
        trades = details = result = equity_curve = metrics = breakdowns = None

        if backtest is not None:
            trades, details = backtest
        if account is not None:
            result, equity_curve = account
        if performance is not None:
            report = performance.report() if hasattr(performance, "report") else performance
            if isinstance(report, dict):
                metrics = report.get("metrics", report)
                breakdowns = {k: v for k, v in report.items()
                              if k not in ("metrics", "equity_curve")
                              and isinstance(v, (pd.DataFrame, pd.Series))}

        return self.save_run(
            run_id, asset=asset, trades=trades, details=details, result=result,
            equity_curve=equity_curve, costed=costed, metrics=metrics, breakdowns=breakdowns,
            extra_metadata=extra_metadata, extra_tables=extra_tables, overwrite=overwrite,
        )

    # ── core save ─────────────────────────────────────────────────────────────

    def save_run(
        self,
        run_id: str,
        *,
        asset: str,
        trades: Optional[pd.DataFrame] = None,
        details: Optional[Dict] = None,
        result: Optional[pd.DataFrame] = None,
        equity_curve: Optional[pd.DataFrame] = None,
        costed: Optional[pd.DataFrame] = None,
        metrics: Optional[Dict] = None,
        breakdowns: Optional[Dict[str, FrameLike]] = None,
        extra_metadata: Optional[Dict] = None,
        extra_tables: Optional[Dict[str, FrameLike]] = None,
        overwrite: bool = False,
    ) -> str:
        """
        Persist one run. Every frame argument is optional, so partial saves work.

        Raises ValueError if `run_id` exists and `overwrite` is False.
        """
        run_id = self._sanitise_run_id(run_id)

        # ── metadata ──────────────────────────────────────────────────────────
        metadata: Dict[str, Any] = {}
        if isinstance(details, dict) and isinstance(details.get("metadata"), dict):
            metadata.update(details["metadata"])
        if extra_metadata:
            metadata.update(extra_metadata)
        saved_at = datetime.now(timezone.utc).isoformat()
        metadata.update({"run_id": run_id, "asset": asset,
                         "saved_at": saved_at, "schema_version": self.SCHEMA_VERSION})
        metrics = dict(metrics) if metrics else {}

        # ── collect artifacts (name → frame/series) ───────────────────────────
        artifacts: Dict[str, FrameLike] = {}

        def _add(name: str, obj):
            if isinstance(obj, (pd.DataFrame, pd.Series)):
                artifacts[name] = obj

        _add("trades", trades)
        if isinstance(details, dict):
            _add("trades_full", details.get("trades"))
            _add("swings", details.get("swings"))
            _add("choch_events", details.get("choch_events"))
        _add("result", result)
        _add("equity_curve", equity_curve)
        _add("costed", costed)
        for k, v in (breakdowns or {}).items():
            if k != "equity_curve":
                _add(f"perf::{k}", v)
        for k, v in (extra_tables or {}).items():
            _add(f"extra::{k}", v)

        headline = self._headline(metrics)

        conn = self._connect()
        try:
            exists = conn.execute("SELECT 1 FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if exists and not overwrite:
                raise ValueError(
                    f"run_id '{run_id}' already exists. Pass overwrite=True to replace it."
                )
            with conn:   # single transaction
                if exists:
                    conn.execute("DELETE FROM artifacts WHERE run_id=?", (run_id,))
                    conn.execute("DELETE FROM runs WHERE run_id=?", (run_id,))
                conn.execute(
                    f"INSERT INTO runs (run_id, asset, saved_at, "
                    f"{', '.join(self.HEADLINE_KEYS)}, metadata_json, metrics_json) "
                    f"VALUES ({', '.join(['?'] * (3 + len(self.HEADLINE_KEYS) + 2))})",
                    (run_id, asset, saved_at,
                     *[headline.get(k) for k in self.HEADLINE_KEYS],
                     json.dumps(self._clean(metadata), default=str),
                     json.dumps(self._clean(metrics), default=str)),
                )
                for name, obj in artifacts.items():
                    payload = self._prepare_frame(obj) if isinstance(obj, pd.DataFrame) else obj
                    kind, blob = _to_blob(payload, self.compression)
                    conn.execute(
                        "INSERT INTO artifacts (run_id, name, kind, data) VALUES (?,?,?,?)",
                        (run_id, name, kind, sqlite3.Binary(blob)),
                    )
        finally:
            conn.close()
        return run_id

    # ── load ───────────────────────────────────────────────────────────────────

    def load_run(self, run_id: str) -> Dict[str, Any]:
        """
        Load every saved artifact for a run.

        Returns a dict with: run_id, asset, saved_at, metadata, metrics, any of
        {trades, trades_full, swings, choch_events, result, equity_curve} that
        were saved, plus "breakdowns" (perf frames) and "extra" (extra tables).
        """
        run_id = self._sanitise_run_id(run_id)
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT asset, saved_at, metadata_json, metrics_json FROM runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"run_id '{run_id}' not found in store.")
            arts = conn.execute(
                "SELECT name, kind, data FROM artifacts WHERE run_id=?", (run_id,)
            ).fetchall()
        finally:
            conn.close()

        out: Dict[str, Any] = {
            "run_id": run_id,
            "asset": row[0],
            "saved_at": row[1],
            "metadata": json.loads(row[2]) if row[2] else {},
            "metrics": json.loads(row[3]) if row[3] else {},
            "breakdowns": {},
            "extra": {},
        }
        for name, kind, blob in arts:
            obj = _from_blob(kind, bytes(blob))
            if name.startswith("perf::"):
                out["breakdowns"][name[len("perf::"):]] = obj
            elif name.startswith("extra::"):
                out["extra"][name[len("extra::"):]] = obj
            else:
                out[name] = obj
        return out

    # ── catalog queries ─────────────────────────────────────────────────────────

    def list_runs(self, asset: Optional[str] = None) -> List[str]:
        """All run_ids (optionally filtered by asset), oldest-saved first."""
        conn = self._connect()
        try:
            if asset is None:
                rows = conn.execute("SELECT run_id FROM runs ORDER BY saved_at").fetchall()
            else:
                rows = conn.execute(
                    "SELECT run_id FROM runs WHERE asset=? ORDER BY saved_at", (asset,)
                ).fetchall()
        finally:
            conn.close()
        return [r[0] for r in rows]

    def list_assets(self) -> List[str]:
        """Distinct assets present in the store."""
        conn = self._connect()
        try:
            rows = conn.execute("SELECT DISTINCT asset FROM runs ORDER BY asset").fetchall()
        finally:
            conn.close()
        return [r[0] for r in rows]

    def summary_table(self, asset: Optional[str] = None) -> pd.DataFrame:
        """One row per run with the headline metrics — fast, SQL-backed."""
        cols = ["run_id", "asset", "saved_at"] + self.HEADLINE_KEYS
        sql = f"SELECT {', '.join(cols)} FROM runs"
        params: Tuple = ()
        if asset is not None:
            sql += " WHERE asset=?"
            params = (asset,)
        sql += " ORDER BY saved_at"
        conn = self._connect()
        try:
            return pd.read_sql_query(sql, conn, params=params)
        finally:
            conn.close()

    def load_metadata(self, run_id: str) -> Dict[str, Any]:
        return self._load_json(run_id, "metadata_json")

    def load_metrics(self, run_id: str) -> Dict[str, Any]:
        return self._load_json(run_id, "metrics_json")

    def load_all_metadata(self) -> pd.DataFrame:
        """Wide DataFrame: every run's full metadata, one row per run."""
        return self._load_all_json("metadata_json")

    def load_all_metrics(self) -> pd.DataFrame:
        """Wide DataFrame: every run's full metrics, one row per run."""
        return self._load_all_json("metrics_json")

    # ── delete / existence ───────────────────────────────────────────────────────

    def delete_run(self, run_id: str) -> None:
        run_id = self._sanitise_run_id(run_id)
        conn = self._connect()
        try:
            if conn.execute("SELECT 1 FROM runs WHERE run_id=?", (run_id,)).fetchone() is None:
                raise KeyError(f"run_id '{run_id}' not found in store.")
            with conn:
                conn.execute("DELETE FROM artifacts WHERE run_id=?", (run_id,))
                conn.execute("DELETE FROM runs WHERE run_id=?", (run_id,))
        finally:
            conn.close()

    delete = delete_run  # backwards-compatible alias

    def exists(self, run_id: str) -> bool:
        run_id = self._sanitise_run_id(run_id)
        conn = self._connect()
        try:
            return conn.execute("SELECT 1 FROM runs WHERE run_id=?", (run_id,)).fetchone() is not None
        finally:
            conn.close()

    # ── private helpers ──────────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.filepath)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _ensure_schema(self) -> None:
        headline_cols = ",\n  ".join(
            f"{k} {'INTEGER' if k == 'total_trades' else 'REAL'}" for k in self.HEADLINE_KEYS
        )
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    f"CREATE TABLE IF NOT EXISTS runs (\n"
                    f"  run_id TEXT PRIMARY KEY,\n"
                    f"  asset TEXT,\n"
                    f"  saved_at TEXT,\n"
                    f"  {headline_cols},\n"
                    f"  metadata_json TEXT,\n"
                    f"  metrics_json TEXT\n)"
                )
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS artifacts (\n"
                    "  run_id TEXT,\n"
                    "  name TEXT,\n"
                    "  kind TEXT,\n"
                    "  data BLOB,\n"
                    "  PRIMARY KEY (run_id, name),\n"
                    "  FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE\n)"
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_asset ON runs(asset)")
        finally:
            conn.close()

    def _load_json(self, run_id: str, column: str) -> Dict[str, Any]:
        run_id = self._sanitise_run_id(run_id)
        conn = self._connect()
        try:
            row = conn.execute(f"SELECT {column} FROM runs WHERE run_id=?", (run_id,)).fetchone()
        finally:
            conn.close()
        if row is None:
            raise KeyError(f"run_id '{run_id}' not found in store.")
        return json.loads(row[0]) if row[0] else {}

    def _load_all_json(self, column: str) -> pd.DataFrame:
        conn = self._connect()
        try:
            rows = conn.execute(f"SELECT run_id, {column} FROM runs ORDER BY saved_at").fetchall()
        finally:
            conn.close()
        records = []
        for rid, blob in rows:
            d = json.loads(blob) if blob else {}
            d.setdefault("run_id", rid)
            records.append(d)
        return pd.json_normalize(records) if records else pd.DataFrame()

    def _headline(self, metrics: Dict) -> Dict[str, Any]:
        return {k: self._scalar(metrics.get(k)) for k in self.HEADLINE_KEYS}

    @staticmethod
    def _scalar(v) -> Optional[Union[int, float]]:
        v = ResultStore._clean(v)
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    @staticmethod
    def _clean(obj):
        """Recursively coerce numpy / NaN / timestamps into JSON-safe values."""
        if isinstance(obj, dict):
            return {str(k): ResultStore._clean(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [ResultStore._clean(v) for v in obj]
        if isinstance(obj, np.generic):
            obj = obj.item()
        if obj is pd.NaT:
            return None
        if isinstance(obj, float):
            return None if (math.isnan(obj) or math.isinf(obj)) else obj
        if isinstance(obj, pd.Timestamp):
            return obj.isoformat()
        if isinstance(obj, (int, bool, str)) or obj is None:
            return obj
        return str(obj)

    @staticmethod
    def _sanitise_run_id(run_id: str) -> str:
        return "_".join(str(run_id).strip().split())

    @staticmethod
    def _prepare_frame(df: pd.DataFrame) -> pd.DataFrame:
        """Coerce dtypes Parquet can't represent (Categorical, dict/list cells)."""
        df = df.copy()
        for col in df.columns:
            if isinstance(df[col].dtype, pd.CategoricalDtype):
                df[col] = df[col].astype(str)
            elif df[col].dtype == object:
                df[col] = df[col].apply(
                    lambda x: json.dumps(x) if isinstance(x, (dict, list)) else x
                )
        return df


# ─────────────────────────────────────────────────────────────────────────────
# demo — full chain saved/loaded under one run for one asset
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import tempfile
    from backtester import CHOCHFibBacktester      # noqa: F401  (illustrative)
    from cfd_costs import CFDCostModel              # noqa: F401
    from account import CFDAccountSimulator
    from performance import PerformanceAnalytics

    # build a synthetic details["trades"] frame and run it through the pipeline
    rng = np.random.default_rng(3)
    rows, t = [], pd.Timestamp("2024-01-02 08:00")
    for k in range(50):
        t += pd.Timedelta(hours=float(rng.integers(6, 50)))
        side = rng.choice(["long", "short"]); entry = 2000 + rng.normal(0, 30)
        sld = rng.uniform(3, 9); roll = rng.random()
        if roll < 0.1:
            rows.append({"trade_id": f"T{k:05d}", "side": side, "setup_time": t,
                         "entry_time": None, "entry_price": None,
                         "exit_time": t + pd.Timedelta(hours=2), "exit_price": None,
                         "sl_price": None, "exit_reason": "Invalidation"}); continue
        sl = entry - sld if side == "long" else entry + sld
        move = (sld * rng.uniform(1.5, 2.4) if roll < 0.55
                else (-sld if roll < 0.85 else sld * rng.uniform(-0.4, 0.5)))
        reason = "TP" if roll < 0.55 else ("SL" if roll < 0.85 else "timeout")
        exit_p = entry + move if side == "long" else entry - move
        rows.append({"trade_id": f"T{k:05d}", "side": side,
                     "setup_time": t - pd.Timedelta(hours=2), "entry_time": t,
                     "entry_price": round(entry, 2),
                     "exit_time": t + pd.Timedelta(hours=float(rng.integers(2, 30))),
                     "exit_price": round(exit_p, 2), "sl_price": round(sl, 2),
                     "exit_reason": reason})
    trades_full = pd.DataFrame(rows)
    details = {"trades": trades_full,
               "swings": pd.DataFrame({"bar": [1, 2], "type": ["high", "low"], "price": [2030.0, 1980.0]}),
               "choch_events": pd.DataFrame({"bar": [3], "direction": ["bullish"]}),
               "metadata": {"run_id": "XAUUSD_1h_fib50", "timeframes": "1h",
                            "entry_fib_level": 0.5, "use_atr_sl_tp": False}}
    slim = trades_full[["trade_id", "side", "setup_time", "entry_time",
                        "entry_price", "exit_time", "exit_price", "exit_reason"]]

    sim = CFDAccountSimulator(symbol="XAUUSD", initial_capital=10_000,
                              use_risk_sizing=True, risk_per_trade=0.01, leverage=20.0)
    result, equity_curve = sim.simulate(trades_full)
    perf = PerformanceAnalytics(result, equity_curve, risk_free_rate=0.04, rolling_trades=8)

    with tempfile.TemporaryDirectory() as d:
        store = ResultStore(os.path.join(d, "all_backtests.db"))
        store.save_pipeline(
            "XAUUSD_1h_fib50", asset="XAUUSD",
            backtest=(slim, details), account=(result, equity_curve),
            performance=perf.report(),
            extra_metadata={"initial_capital": 10_000, "leverage": 20, "risk_per_trade": 0.01},
            overwrite=True,
        )
        # a second run for a different asset
        store.save_pipeline("NAS100_1h_fib50", asset="NAS100",
                            account=(result, equity_curve), performance=perf.report())

        print("assets   :", store.list_assets())
        print("XAUUSD   :", store.list_runs(asset="XAUUSD"))
        print("\nsummary_table:")
        print(store.summary_table().to_string(index=False))

        run = store.load_run("XAUUSD_1h_fib50")
        print("\nloaded artifacts:", [k for k in run if isinstance(run[k], (pd.DataFrame, pd.Series))],
              "| breakdowns:", list(run["breakdowns"]))
        # round-trip integrity
        pd.testing.assert_frame_equal(run["result"].reset_index(drop=True),
                                      result.reset_index(drop=True))
        pd.testing.assert_frame_equal(run["equity_curve"].reset_index(drop=True),
                                      equity_curve.reset_index(drop=True))
        print("[check] result & equity_curve round-trip exactly  ✓")
        print("[check] net_profit in catalog:", run["metrics"]["net_profit"])