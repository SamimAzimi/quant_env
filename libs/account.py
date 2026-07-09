"""
account.py — CFDAccountSimulator

Turns a per-trade ledger into an account simulation: it sizes each position
(fixed lots, or risk-based "if selected"), prices it through CFDCostModel,
walks the trades in time order while compounding equity, and returns

    result_df, equity_curve = sim.simulate(trades)

result_df is the input frame plus, per trade:
    risk_distance     |entry − stop| in price terms
    risk_per_trade    the risk budget used to size the trade (account ccy)
    capital_at_risk   actual loss if the stop is hit  = risk_distance × units × fx
    capital_used      margin tied up = notional / leverage
    lots, units, notional
    spread_cost, commission_cost, financing_cost, total_cost   (from CFDCostModel)
    gross_pnl, net_pnl
    r_multiple        net_pnl / capital_at_risk
    margin_ok         did the required margin fit inside equity_before?
    equity_before, equity_after

equity_curve is a tidy frame (one row per event + a START row) with the running
equity, peak, drawdown and drawdown_pct — ready to plot.

──────────────────────────────────────────────────────────────────────────────
This layer needs the STOP price (for risk_distance and risk sizing). The slim
trades_df does NOT carry it — pass ``details["trades"]`` from
``CHOCHFibBacktester.backtest()`` (or merge an ``sl_price`` column in).
Leverage is broker/asset/regulator specific — set it for the instrument you're
running. Defaults here are illustrative.   Not financial advice.
──────────────────────────────────────────────────────────────────────────────

Usage
-----
    from backtester import CHOCHFibBacktester
    from cfd_costs import CFDCostModel
    from account import CFDAccountSimulator

    trades_df, details = CHOCHFibBacktester(run_id="NAS100_1h").backtest(df)

    sim = CFDAccountSimulator(
        symbol="NAS100",
        initial_capital=10_000,
        use_risk_sizing=True, risk_mode="percent", risk_per_trade=0.01,  # 1%/trade
        leverage=20.0,
    )
    result, curve = sim.simulate(details["trades"])   # needs sl_price
    print(sim.stats(result, curve))
"""
from __future__ import annotations

import math
import warnings
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

from .cfd_cost import CFDCostModel


class CFDAccountSimulator:
    """
    Parameters
    ----------
    cost_model : CFDCostModel, optional
        Pre-built cost model. If omitted, one is built from `symbol` + any extra
        cost kwargs (lots, fx_rate, apply_financing, spread_points, ...).
    symbol : str, optional
        Instrument symbol, used only when `cost_model` is not supplied.
    initial_capital : float, default 10_000
        Starting account equity (account currency).
    use_risk_sizing : bool, default False
        If True, size each trade from its stop distance and the risk budget.
        If False, use the cost model's fixed `lots`.
    risk_mode : {"percent", "fixed"}, default "percent"
        "percent" → budget = risk_per_trade × equity_before (compounds).
        "fixed"   → budget = risk_per_trade (constant account-ccy amount).
    risk_per_trade : float, default 0.01
        Risk budget. A fraction (0.01 = 1%) in "percent" mode, or an absolute
        account-ccy amount in "fixed" mode.
    leverage : float, default 30.0
        Used only to report margin (capital_used = notional / leverage).
    lot_step, min_lots : float, optional
        Round the sized lots down to `lot_step`; trades below `min_lots` after
        rounding are skipped (no position taken).
    """

    _EXTRA_COLS = [
        "risk_distance", "risk_per_trade", "capital_at_risk", "capital_used",
        "lots", "units", "notional",
        "spread_cost", "commission_cost", "financing_cost", "total_cost",
        "gross_pnl", "net_pnl", "r_multiple", "margin_ok",
        "equity_before", "equity_after",
    ]

    def __init__(
        self,
        cost_model: Optional[CFDCostModel] = None,
        *,
        symbol: Optional[str] = None,
        initial_capital: float = 10_000.0,
        use_risk_sizing: bool = False,
        risk_mode: str = "percent",
        risk_per_trade: float = 0.01,
        leverage: float = 30.0,
        lot_step: Optional[float] = None,
        min_lots: float = 0.0,
        **cost_kwargs,
    ) -> None:
        if cost_model is None:
            cost_model = CFDCostModel(symbol=symbol, **cost_kwargs)
        if risk_mode not in ("percent", "fixed"):
            raise ValueError("risk_mode must be 'percent' or 'fixed'")

        self.cost_model      = cost_model
        self.initial_capital = float(initial_capital)
        self.use_risk_sizing = bool(use_risk_sizing)
        self.risk_mode       = risk_mode
        self.risk_per_trade  = float(risk_per_trade)
        self.leverage        = float(leverage)
        self.lot_step        = lot_step
        self.min_lots        = float(min_lots)

    # ── main entry point ─────────────────────────────────────────────────────

    def simulate(self, trades: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """Run the account simulation. Returns ``(result_df, equity_curve)``."""
        df = trades.copy().reset_index(drop=True)
        cm, spec, fx, cs = self.cost_model, self.cost_model.spec, \
            self.cost_model.fx_rate, self.cost_model.spec.contract_size

        has_sl = "sl_price" in df.columns
        if self.use_risk_sizing and not has_sl:
            raise ValueError(
                "Risk-based sizing needs an 'sl_price' column. Pass "
                "details['trades'] from the backtester (the slim trades_df "
                "does not carry the stop), or merge sl_price in."
            )

        equity = self.initial_capital
        start_time = self._first_time(df)
        curve = [{"step": 0, "time": start_time, "trade_id": "START",
                  "equity": equity}]
        records = []

        for i in range(len(df)):
            row    = df.iloc[i]
            entry  = pd.to_numeric(pd.Series([row.get("entry_price")]), errors="coerce").iloc[0]
            exit_  = pd.to_numeric(pd.Series([row.get("exit_price")]),  errors="coerce").iloc[0]
            filled = pd.notna(entry) and pd.notna(exit_)
            rec    = {c: np.nan for c in self._EXTRA_COLS}
            rec["equity_before"] = equity

            if not filled:
                # invalidation / no-fill: no risk, no capital, equity unchanged
                rec["equity_after"] = equity
                records.append(rec)
                curve.append({"step": i + 1, "time": row.get("exit_time"),
                              "trade_id": row.get("trade_id"), "equity": equity})
                continue

            sl        = pd.to_numeric(pd.Series([row.get("sl_price")]), errors="coerce").iloc[0] if has_sl else np.nan
            risk_dist = abs(entry - sl) if pd.notna(sl) else np.nan

            # ── position sizing ───────────────────────────────────────────────
            if self.use_risk_sizing:
                if pd.isna(risk_dist) or risk_dist <= 0:
                    warnings.warn(f"trade {row.get('trade_id')}: invalid stop "
                                  f"distance, skipped.")
                    rec["equity_after"] = equity
                    records.append(rec)
                    curve.append({"step": i + 1, "time": row.get("exit_time"),
                                  "trade_id": row.get("trade_id"), "equity": equity})
                    continue
                budget = (self.risk_per_trade * equity if self.risk_mode == "percent"
                          else self.risk_per_trade)
                units  = budget / (risk_dist * fx)
                lots   = units / cs
            else:
                lots  = cm.lots
                units = lots * cs

            lots  = self._round_lots(lots)
            units = lots * cs
            if lots <= 0:                       # below min size → cannot trade
                rec["equity_after"] = equity
                records.append(rec)
                curve.append({"step": i + 1, "time": row.get("exit_time"),
                              "trade_id": row.get("trade_id"), "equity": equity})
                continue

            # ── cost & P&L via the cost model (single source of truth) ────────
            one = df.iloc[[i]].copy()
            one["lots"] = lots
            c = cm.add_costs(one).iloc[0]

            notional        = entry * units * fx                 # account ccy
            capital_used    = notional / self.leverage if self.leverage else notional
            capital_at_risk = risk_dist * units * fx if pd.notna(risk_dist) else np.nan
            if self.use_risk_sizing:
                risk_budget = (self.risk_per_trade * equity if self.risk_mode == "percent"
                               else self.risk_per_trade)
            else:                                # fixed lots → report implied risk
                risk_budget = capital_at_risk

            net = float(c["net_pnl"])
            equity_after = equity + net

            rec.update({
                "risk_distance":   risk_dist,
                "risk_per_trade":  risk_budget,
                "capital_at_risk": capital_at_risk,
                "capital_used":    capital_used,
                "lots":            lots,
                "units":           units,
                "notional":        notional,
                "spread_cost":     float(c["spread_cost"]),
                "commission_cost": float(c["commission_cost"]),
                "financing_cost":  float(c["financing_cost"]),
                "total_cost":      float(c["total_cost"]),
                "gross_pnl":       float(c["gross_pnl"]),
                "net_pnl":         net,
                "r_multiple":      (net / capital_at_risk
                                    if capital_at_risk not in (0, np.nan) and pd.notna(capital_at_risk)
                                    else np.nan),
                "margin_ok":       bool(capital_used <= equity),
                "equity_before":   equity,
                "equity_after":    equity_after,
            })
            records.append(rec)
            equity = equity_after
            curve.append({"step": i + 1, "time": row.get("exit_time"),
                          "trade_id": row.get("trade_id"), "equity": equity})

        result = pd.concat(
            [df, pd.DataFrame(records, index=df.index)], axis=1
        )
        return result, self._build_curve(curve)

    # ── helpers ──────────────────────────────────────────────────────────────

    def _round_lots(self, lots: float) -> float:
        if self.lot_step:
            lots = math.floor(lots / self.lot_step + 1e-9) * self.lot_step
        if lots < self.min_lots:
            return 0.0
        return lots

    @staticmethod
    def _first_time(df: pd.DataFrame):
        for col in ("setup_time", "entry_time", "exit_time"):
            if col in df.columns:
                s = df[col].dropna()
                if len(s):
                    return s.iloc[0]
        return pd.NaT

    @staticmethod
    def _build_curve(curve_rows) -> pd.DataFrame:
        curve = pd.DataFrame(curve_rows)
        peak = curve["equity"].cummax()
        curve["peak"]         = peak
        curve["drawdown"]     = curve["equity"] - peak
        curve["drawdown_pct"] = np.where(peak != 0,
                                         curve["drawdown"] / peak * 100.0, 0.0)
        return curve

    # ── headline stats (optional convenience) ────────────────────────────────

    def stats(self, result: pd.DataFrame, curve: pd.DataFrame) -> Dict:
        d = result[result["net_pnl"].notna()]
        wins, losses = d[d["net_pnl"] > 0], d[d["net_pnl"] < 0]
        gross_profit = float(wins["net_pnl"].sum())
        gross_loss   = float(losses["net_pnl"].sum())
        final_equity = float(curve["equity"].iloc[-1])
        return {
            "symbol":            self.cost_model.spec.symbol,
            "initial_capital":   round(self.initial_capital, 2),
            "final_equity":      round(final_equity, 2),
            "total_return_pct":  round((final_equity / self.initial_capital - 1) * 100, 2),
            "trades":            int(len(d)),
            "win_rate_pct":      round(100 * len(wins) / len(d), 2) if len(d) else None,
            "total_cost":        round(float(d["total_cost"].sum()), 2),
            "net_pnl":           round(float(d["net_pnl"].sum()), 2),
            "profit_factor":     round(gross_profit / abs(gross_loss), 2) if gross_loss else None,
            "avg_r_multiple":    round(float(d["r_multiple"].mean()), 2) if len(d) else None,
            "max_drawdown_pct":  round(float(curve["drawdown_pct"].min()), 2),
        }


# ─────────────────────────────────────────────────────────────────────────────
# demo
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # rich frame shaped like details["trades"] (note: includes sl_price)
    trades = pd.DataFrame([
        {"trade_id": "T00001", "side": "long",
         "setup_time": pd.Timestamp("2024-01-01 09:00"),
         "entry_time": pd.Timestamp("2024-01-01 12:00"), "entry_price": 18000.0,
         "exit_time":  pd.Timestamp("2024-01-02 15:00"), "exit_price": 18100.0,
         "sl_price": 17950.0, "exit_reason": "TP"},
        {"trade_id": "T00002", "side": "short",
         "setup_time": pd.Timestamp("2024-01-03 09:00"),
         "entry_time": pd.Timestamp("2024-01-03 10:00"), "entry_price": 18080.0,
         "exit_time":  pd.Timestamp("2024-01-03 16:00"), "exit_price": 18130.0,
         "sl_price": 18130.0, "exit_reason": "SL"},
        {"trade_id": "T00003", "side": "long",   # invalidation, never filled
         "setup_time": pd.Timestamp("2024-01-04 09:00"),
         "entry_time": None, "entry_price": None,
         "exit_time":  pd.Timestamp("2024-01-04 11:00"), "exit_price": None,
         "sl_price": None, "exit_reason": "Invalidation"},
        {"trade_id": "T00004", "side": "long",
         "setup_time": pd.Timestamp("2024-01-05 09:00"),
         "entry_time": pd.Timestamp("2024-01-05 12:00"), "entry_price": 18050.0,
         "exit_time":  pd.Timestamp("2024-01-08 15:00"), "exit_price": 18250.0,
         "sl_price": 17975.0, "exit_reason": "TP"},
    ])

    sim = CFDAccountSimulator(
        symbol="NAS100", initial_capital=10_000,
        use_risk_sizing=True, risk_mode="percent", risk_per_trade=0.01,  # 1%/trade
        leverage=20.0,
    )
    result, curve = sim.simulate(trades)

    show = ["trade_id", "side", "exit_reason", "risk_distance", "lots",
            "risk_per_trade", "capital_at_risk", "capital_used",
            "total_cost", "net_pnl", "r_multiple",
            "equity_before", "equity_after"]
    print(result[show].to_string(index=False))
    print("\nEquity curve:")
    print(curve.to_string(index=False))
    print("\nStats:", sim.stats(result, curve))