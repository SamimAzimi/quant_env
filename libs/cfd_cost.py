"""
cfd_costs.py — CFDCostModel

Takes the slim `trades_df` produced by ``CHOCHFibBacktester.backtest()`` and
returns a copy with CFD trading costs (and resulting P&L) appended.

It models the three costs a CFD account actually charges on a position:

    spread       — paid once across the round trip (buy at ask, sell at bid)
    commission   — per-lot and/or % of notional, charged on open + close
    financing    — overnight swap / rollover, charged per night held on notional

and supports the asset classes you trade:

    forex        EURUSD, GBPUSD, USDJPY, ...   (1 lot = 100,000 units)
    commodities  XAUUSD (gold), XAGUSD (silver), USOIL / UKOIL
    indices      NAS100, SPX500, US30, GER40   (1 lot = 1 currency unit / point)

──────────────────────────────────────────────────────────────────────────────
⚠️  THE NUMBERS IN ``DEFAULT_SPECS`` ARE ILLUSTRATIVE PLACEHOLDERS.
    Spreads, commissions, contract sizes and swap rates differ by broker and
    change over time. Override them with your broker's contract specs before
    trusting any cost figure (see the override kwargs on CFDCostModel, or edit
    DEFAULT_SPECS / pass your own InstrumentSpec).
──────────────────────────────────────────────────────────────────────────────

This is a backtesting cost utility, not financial advice.

Usage
-----
    from backtester import CHOCHFibBacktester
    from cfd_costs import CFDCostModel

    trades_df, details = CHOCHFibBacktester(run_id="XAUUSD_1h").backtest(df)

    costs = CFDCostModel("XAUUSD", lots=1.0)          # gold, 1 standard lot
    costed = costs.add_costs(trades_df)               # original df + cost columns
    print(costs.summary(costed))

Columns added: units, notional, nights_held, spread_cost, commission_cost,
financing_cost, total_cost, gross_pnl, net_pnl. All monetary outputs are in the
account currency (= quote currency × ``fx_rate``; leave fx_rate=1.0 for
USD-quoted instruments on a USD account).
"""
from __future__ import annotations

import warnings
from dataclasses import replace
from typing import Dict, Optional
import pandas as pd
from config.config import InstrumentSpec,_FOREX_TEMPLATE,DEFAULT_SPECS,_ALIASES


def get_spec(symbol: str) -> InstrumentSpec:
    """Resolve a symbol (case / punctuation insensitive, with aliases) to a spec."""
    key = "".join(ch for ch in symbol.upper() if ch.isalnum())
    if key in DEFAULT_SPECS:
        return DEFAULT_SPECS[key]
    if key in _ALIASES:
        return DEFAULT_SPECS[_ALIASES[key]]
    # unknown but looks like a 6-char FX pair → fall back to the forex template
    if len(key) == 6 and key.isalpha():
        quote = key[3:]
        return replace(_FOREX_TEMPLATE, symbol=key,
                       point_size=0.01 if quote == "JPY" else 0.0001,
                       quote_currency=quote)
    raise KeyError(
        f"No spec for {symbol!r}. Pass a custom InstrumentSpec(spec=...) "
        f"or add it to DEFAULT_SPECS."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Cost model
# ─────────────────────────────────────────────────────────────────────────────

class CFDCostModel:
    """
    Price the costs of a `trades_df` for a single CFD instrument.

    Parameters
    ----------
    symbol : str, optional
        Instrument to look up in DEFAULT_SPECS (e.g. "EURUSD", "XAUUSD",
        "NAS100"). Ignored if `spec` is given.
    spec : InstrumentSpec, optional
        Provide a fully custom spec instead of a symbol lookup.
    lots : float, default 1.0
        Position size in lots, applied to every trade. (If `trades_df` has a
        per-trade ``lots`` column, that column is used instead.)
    fx_rate : float, default 1.0
        Quote-currency → account-currency conversion. Leave at 1.0 for
        USD-quoted instruments on a USD account; set e.g. ~1/150 for a
        JPY-quoted pair into a USD account.
    apply_financing : bool, default True
        Charge overnight financing. Requires datetime entry/exit times
        (i.e. the OHLC frame had a "Datetime" column). If times are bar
        indices, financing is skipped with a warning.
    spread_round_trips : float, default 1.0
        How many spreads the round trip costs. 1.0 is correct for a normal
        open+close; set 2.0 only if you want to double-charge the spread.

    Override kwargs (spread_points, commission_per_lot, commission_pct,
    overnight_fee_long, overnight_fee_short, contract_size, point_size,
    quote_currency) replace the matching field on the resolved spec.
    """

    COST_COLUMNS = [
        "units", "notional", "nights_held",
        "spread_cost", "commission_cost", "financing_cost", "total_cost",
        "gross_pnl", "net_pnl",
    ]
    _SIDE_SIGN = {"long": 1, "short": -1}

    def __init__(
        self,
        symbol: Optional[str] = None,
        spec: Optional[InstrumentSpec] = None,
        *,
        lots: float = 1.0,
        fx_rate: float = 1.0,
        apply_financing: bool = True,
        spread_round_trips: float = 1.0,
        # spec overrides
        spread_points: Optional[float] = None,
        commission_per_lot: Optional[float] = None,
        commission_pct: Optional[float] = None,
        overnight_fee_long: Optional[float] = None,
        overnight_fee_short: Optional[float] = None,
        contract_size: Optional[float] = None,
        point_size: Optional[float] = None,
        quote_currency: Optional[str] = None,
    ) -> None:
        if spec is None:
            if symbol is None:
                raise ValueError("Provide either `symbol` or `spec`.")
            spec = get_spec(symbol)

        overrides = {
            k: v for k, v in dict(
                spread_points=spread_points,
                commission_per_lot=commission_per_lot,
                commission_pct=commission_pct,
                overnight_fee_long=overnight_fee_long,
                overnight_fee_short=overnight_fee_short,
                contract_size=contract_size,
                point_size=point_size,
                quote_currency=quote_currency,
            ).items() if v is not None
        }
        self.spec               = replace(spec, **overrides) if overrides else spec
        self.lots               = float(lots)
        self.fx_rate            = float(fx_rate)
        self.apply_financing    = bool(apply_financing)
        self.spread_round_trips = float(spread_round_trips)
        self._warned_nights     = False

    # ── main entry point ─────────────────────────────────────────────────────

    def add_costs(self, trades_df: pd.DataFrame) -> pd.DataFrame:
        """Return a copy of `trades_df` with cost and P&L columns appended."""
        df   = trades_df.copy()
        spec = self.spec

        if df.empty:
            for col in self.COST_COLUMNS:
                df[col] = pd.Series(dtype="float64")
            return df

        sign  = df["side"].map(self._SIDE_SIGN)
        entry = pd.to_numeric(df["entry_price"], errors="coerce")
        exit_ = pd.to_numeric(df["exit_price"],  errors="coerce")
        # an actual fill (invalidation rows have no entry/exit price)
        filled = entry.notna() & exit_.notna()

        # position size → units of the underlying
        if "lots" in df.columns:
            lots = pd.to_numeric(df["lots"], errors="coerce").fillna(self.lots)
        else:
            lots = pd.Series(self.lots, index=df.index, dtype="float64")
        units    = lots * spec.contract_size
        notional = entry * units                         # in quote currency

        # ── spread (round trip) ───────────────────────────────────────────────
        spread_price = spec.spread_points * spec.point_size
        spread_cost  = spread_price * units * self.spread_round_trips

        # ── commission (open + close) ─────────────────────────────────────────
        commission_cost = (spec.commission_per_lot * lots
                           + spec.commission_pct * notional * 2.0)

        # ── overnight financing ───────────────────────────────────────────────
        nights = self._nights_held(df)
        if self.apply_financing:
            daily_rate     = sign.map({1: spec.overnight_fee_long,
                                       -1: spec.overnight_fee_short}).fillna(0.0)
            financing_cost = notional * daily_rate * nights
        else:
            financing_cost = pd.Series(0.0, index=df.index)

        # convert quote-ccy costs to account ccy, then zero-out non-fills
        spread_cost     = (spread_cost     * self.fx_rate).where(filled, 0.0)
        commission_cost = (commission_cost * self.fx_rate).where(filled, 0.0)
        financing_cost  = (financing_cost  * self.fx_rate).where(filled, 0.0)
        total_cost      = spread_cost + commission_cost + financing_cost

        # ── P&L ───────────────────────────────────────────────────────────────
        gross_pnl = ((exit_ - entry) * units * sign * self.fx_rate).where(filled)
        net_pnl   = gross_pnl - total_cost

        df["units"]           = units.where(filled)
        df["notional"]        = notional.where(filled)
        df["nights_held"]     = nights.where(filled)
        df["spread_cost"]     = spread_cost
        df["commission_cost"] = commission_cost
        df["financing_cost"]  = financing_cost
        df["total_cost"]      = total_cost
        df["gross_pnl"]       = gross_pnl
        df["net_pnl"]         = net_pnl
        return df

    # ── helpers ──────────────────────────────────────────────────────────────

    def _nights_held(self, df: pd.DataFrame) -> pd.Series:
        """
        Number of nights a position is held = count of calendar date rollovers
        between entry and exit. Includes weekends (most index/commodity CFDs
        accrue weekend financing; forex often triples on Wednesday — refine here
        if that matters to you). Returns 0 when times are bar indices, not dates.
        """
        et, xt = df["entry_time"], df["exit_time"]
        if pd.api.types.is_numeric_dtype(et) or pd.api.types.is_numeric_dtype(xt):
            if self.apply_financing and not self._warned_nights:
                warnings.warn(
                    "entry/exit times are bar indices, not datetimes — overnight "
                    "financing set to 0. Add a 'Datetime' column to the OHLC frame "
                    "so the backtester emits timestamps."
                )
                self._warned_nights = True
            return pd.Series(0, index=df.index)

        et = pd.to_datetime(et, errors="coerce")
        xt = pd.to_datetime(xt, errors="coerce")
        nights = (xt.dt.normalize() - et.dt.normalize()).dt.days
        return nights.fillna(0).clip(lower=0).astype("int64")

    def summary(self, costed_df: pd.DataFrame) -> Dict:
        """Aggregate the costs/P&L of a frame returned by ``add_costs``."""
        d = costed_df[costed_df["net_pnl"].notna()]
        gross = float(d["gross_pnl"].sum())
        cost  = float(d["total_cost"].sum())
        return {
            "symbol":          self.spec.symbol,
            "account_ccy_fx":  self.fx_rate,
            "trades":          int(len(d)),
            "gross_pnl":       round(gross, 2),
            "spread_cost":     round(float(d["spread_cost"].sum()), 2),
            "commission_cost": round(float(d["commission_cost"].sum()), 2),
            "financing_cost":  round(float(d["financing_cost"].sum()), 2),
            "total_cost":      round(cost, 2),
            "net_pnl":         round(gross - cost, 2),
            "cost_pct_of_gross": (round(100 * cost / abs(gross), 2)
                                  if gross else None),
        }


# ─────────────────────────────────────────────────────────────────────────────
# tiny self-contained demo
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    demo = pd.DataFrame([
        # a winning long, held ~2 nights
        {"trade_id": "T00001", "side": "long",
         "setup_time": pd.Timestamp("2024-01-01 09:00"),
         "entry_time": pd.Timestamp("2024-01-01 12:00"), "entry_price": 100.0,
         "exit_time":  pd.Timestamp("2024-01-03 15:00"), "exit_price": 103.0,
         "exit_reason": "TP"},
        # a losing short, same day
        {"trade_id": "T00002", "side": "short",
         "setup_time": pd.Timestamp("2024-01-04 09:00"),
         "entry_time": pd.Timestamp("2024-01-04 10:00"), "entry_price": 102.0,
         "exit_time":  pd.Timestamp("2024-01-04 16:00"), "exit_price": 103.0,
         "exit_reason": "SL"},
        # an invalidated setup — never filled, must cost nothing
        {"trade_id": "T00003", "side": "long",
         "setup_time": pd.Timestamp("2024-01-05 09:00"),
         "entry_time": None, "entry_price": None,
         "exit_time":  pd.Timestamp("2024-01-05 11:00"), "exit_price": None,
         "exit_reason": "Invalidation"},
    ])

    model  = CFDCostModel("NAS100", lots=1.0)
    costed = model.add_costs(demo)
    cols = ["trade_id", "side", "exit_reason", "notional", "nights_held",
            "spread_cost", "financing_cost", "total_cost", "gross_pnl", "net_pnl"]
    print(costed[cols].to_string(index=False))
    print()
    print(model.summary(costed))