"""
pipeline.py — one parameterized entry point for the whole backtest chain.

Wires: data_loader → strategy backtest → CFDAccountSimulator (costs applied
internally) → PerformanceAnalytics → BacktestStore (the Market-Prep app
database, browsable in the web app under Strategies), for one
(asset, timeframe), and batches cleanly over many.

The strategy is injected, so the engine stays independent of any specific
strategy module:

    from libs.pipeline import PipelineConfig, run_pipeline, run_many
    from strategies.hull_strategy_suit import HullSuiteStrategy

    res = run_pipeline(PipelineConfig(asset="NDX", asset_class="I", timeframe="1h",
                                      strategy_cls=HullSuiteStrategy))
    res.metrics                      # flat dict of every KPI
    res.report["exit_reasons"]       # pie-ready frame, etc.

    # or batch several assets into one store, then compare:
    results = run_many([
        PipelineConfig(asset="NDX",    asset_class="I",  cost_symbol="NAS100"),
        PipelineConfig(asset="SPX500", asset_class="I"),
        PipelineConfig(asset="XAUUSD", asset_class="C", use_risk_sizing=True),
    ])

The strategy class must expose
``backtest(df) -> (trades_df, details)`` and accept
``run_id``, ``timeframe``, ``asset_class`` plus its own params as kwargs.
When ``strategy_cls`` is omitted, HullSuiteStrategy is used.
"""
from __future__ import annotations
import sys
from pathlib import Path

# make `libs`/`config`/`strategies` importable from any working directory
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd

from config.config import MARKET_DATA_DIR, DB_DIR
from libs import data_loader
from libs import indicators as ind
from libs.cfd_cost import CFDCostModel
from libs.account import CFDAccountSimulator
from libs.performance import PerformanceAnalytics


def _default_strategy_cls():
    # imported lazily so the engine has no hard dependency on strategies/
    from strategies.hull_strategy_suit import HullSuiteStrategy
    return HullSuiteStrategy

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PipelineConfig:
    # ── identity / data ──────────────────────────────────────────────────────
    asset: str                                   # ticker on disk, e.g. "NDX"
    asset_class: str                             # "I" indices, "C" commodities, "FX" ...
    timeframe: str = "1h"
    run_id: Optional[str] = None                 # default f"{asset}_{timeframe}"
    cost_symbol: Optional[str] = None            # broker symbol for cost specs; default = asset
    #   (CFDCostModel resolves aliases: NDX→NAS100, GOLD→XAUUSD, WTI→USOIL, ...)

    # ── account / sizing ─────────────────────────────────────────────────────
    initial_capital: float = 10_000.0
    use_risk_sizing: bool = False
    risk_mode: str = "percent"                   # used only when use_risk_sizing
    risk_per_trade: float = 0.01
    leverage: float = 20.0
    lots: float = 0.1                            # fixed size when not risk-sizing

    # ── analytics ────────────────────────────────────────────────────────────
    risk_free_rate: float = 0.04
    periods_per_year: int = 252

    # ── strategy ─────────────────────────────────────────────────────────────
    strategy_cls: Optional[type] = None          # default: HullSuiteStrategy
    strategy_params: Dict[str, Any] = field(default_factory=dict)
    atr_length: int = 14

    # ── io / persistence (root-anchored defaults; override per run if needed) ─
    marketdata_path: str = str(MARKET_DATA_DIR) + "/"
    db_path: str = str(DB_DIR) + "/"
    persist: bool = True
    overwrite: bool = True

    def __post_init__(self) -> None:
        self.run_id = self.run_id or f"{self.asset}_{self.timeframe}"
        self.cost_symbol = self.cost_symbol or self.asset

    @property
    def csv_path(self) -> str:
        return f"{self.marketdata_path}{self.asset}/{self.timeframe}.csv"
    @property
    def lower_csv_path(self) -> str:
        return f"{self.marketdata_path}{self.asset}/{self.lower_tf}.csv"

    
    @property
    def db_file(self) -> str:
        return f"{self.db_path}all_backtests.db"

    def metadata(self) -> Dict[str, Any]:
        """Run config worth persisting alongside the results."""
        return {
            "strategy": self.strategy_cls.__name__ if self.strategy_cls else "HullSuiteStrategy",
            "asset_class": self.asset_class,
            "timeframe": self.timeframe,
            "cost_symbol": self.cost_symbol,
            "initial_capital": self.initial_capital,
            "use_risk_sizing": self.use_risk_sizing,
            "risk_mode": self.risk_mode,
            "risk_per_trade": self.risk_per_trade,
            "leverage": self.leverage,
            "lots": self.lots,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Result bundle
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PipelineResult:
    run_id: str
    asset: str
    trades_df: pd.DataFrame
    details: Dict[str, Any]
    result_df: pd.DataFrame
    equity_curve: pd.DataFrame
    costed: pd.DataFrame
    report: Dict[str, Any]
    perf: PerformanceAnalytics
    cost_summary: Dict[str, Any]

    @property
    def metrics(self) -> Dict[str, Any]:
        return self.report["metrics"]


def _make_store(cfg: "PipelineConfig"):
    """Store for this run: the Market-Prep app database (MARKET_PREP_DB_URL),
    where the web app's Strategies page reads it back."""
    try:
        from server.backtest_store import BacktestStore   # lazy: server deps
    except ImportError as exc:
        raise RuntimeError(
            "Persisting a run needs the web-app dependencies so it can be "
            "saved into the Market-Prep database and shown under Strategies: "
            "pip install -e '.[web]'"
        ) from exc
    return BacktestStore(cfg.db_file)


def _cost_summary(result_df: pd.DataFrame) -> Dict[str, Any]:
    """Aggregate the cost columns already present in result_df — no recompute."""
    f = result_df[result_df["net_pnl"].notna()]
    cols = ["spread_cost", "commission_cost", "financing_cost", "total_cost"]
    return {"trades": int(len(f)),
            **{c: round(float(f[c].sum()), 2) for c in cols if c in f.columns}}


# ─────────────────────────────────────────────────────────────────────────────
# Single run
# ─────────────────────────────────────────────────────────────────────────────

def run_pipeline(cfg: PipelineConfig, store: Optional[Any] = None) -> PipelineResult:
    """Run the full chain for one (asset, timeframe) and (optionally) persist it."""
    # 1. data + indicators

    df = data_loader.load_csv(cfg.csv_path)
    df["ATR"] = ind.calculate_atr(df, cfg.atr_length)

    # 2. backtest — strategy is injected via cfg.strategy_cls
    strategy_cls = cfg.strategy_cls or _default_strategy_cls()
    strategy = strategy_cls(run_id=cfg.run_id, timeframe=cfg.timeframe,
                            asset_class=cfg.asset_class, **cfg.strategy_params)
    trades_df, details = strategy.backtest(df)
    # 3. account simulation — the cost model is shared so costs are priced once,
    #    at the actually-sized position (no separate add_costs pass needed)
    cost_model = CFDCostModel(cfg.cost_symbol, lots=cfg.lots)
    costed = cost_model.add_costs(trades_df)        # per-trade cost table (saved with the run)
    sim = CFDAccountSimulator(
        cost_model=cost_model,
        initial_capital=cfg.initial_capital,
        use_risk_sizing=cfg.use_risk_sizing,
        risk_mode=cfg.risk_mode,
        risk_per_trade=cfg.risk_per_trade,
        leverage=cfg.leverage,
    )
    result_df, equity_curve = sim.simulate(details["trades"])   # needs sl_price

    # 4. analytics — compute the report ONCE and reuse it
    perf = PerformanceAnalytics(
        result_df, equity_curve,
        risk_free_rate=cfg.risk_free_rate,
        periods_per_year=cfg.periods_per_year,
    )
    report = perf.report()

    # 5. persist (reuse `report`, don't call perf.report() again)
    if cfg.persist:
        store = store or _make_store(cfg)
        store.save_pipeline(
            run_id=cfg.run_id,
            asset=cfg.asset,
            backtest=(trades_df, details),
            account=(result_df, equity_curve),
            performance=report,
            costed=costed,
            extra_metadata=cfg.metadata(),
            overwrite=cfg.overwrite,
        )
        # say WHERE it went, so "the report doesn't show" is diagnosable
        from server.db import DB_URL
        print(f"[store] run {cfg.run_id!r} saved to {DB_URL} "
              "— web app → Strategies")

    return PipelineResult(
        run_id=cfg.run_id, asset=cfg.asset,
        trades_df=trades_df, details=details,
        result_df=result_df, equity_curve=equity_curve, costed=costed,
        report=report, perf=perf, cost_summary=_cost_summary(result_df),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Batch
# ─────────────────────────────────────────────────────────────────────────────

def run_many(
    configs: List[PipelineConfig],
    store: Optional[Any] = None,
    *,
    raise_on_error: bool = False,
) -> Dict[str, PipelineResult]:
    """
    Run several configs against ONE store (opened once). A failing asset is
    logged and skipped unless `raise_on_error`. Returns {run_id: PipelineResult}.
    """
    if store is None and configs:
        store = _make_store(configs[0])

    results: Dict[str, PipelineResult] = {}
    for cfg in configs:
        try:
            results[cfg.run_id] = run_pipeline(cfg, store=store)
        except Exception as exc:                          # noqa: BLE001
            if raise_on_error:
                raise
            print(f"[skip] {cfg.run_id} ({cfg.asset}): {type(exc).__name__}: {exc}")
    return results

# ─────────────────────────────────────────────────────────────────────────────
# Example usage (guard so importing the module does nothing)
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    res = run_pipeline(PipelineConfig(asset="NDX", asset_class="I", timeframe="1h",
                                      cost_symbol="NAS100"))
    print("cost summary:", res.cost_summary)
    print("net profit  :", res.metrics["net_profit"], "| sharpe:", res.metrics["sharpe"])

    # cross-run comparison after a batch
    from server.backtest_store import BacktestStore
    print(BacktestStore().summary_table().to_string(index=False))