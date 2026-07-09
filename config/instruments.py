# ─────────────────────────────────────────────────────────────────────────────
# CFD instrument specifications (consumed by libs/cfd_cost.py)
# ─────────────────────────────────────────────────────────────────────────────

from dataclasses import dataclass, replace
from typing import Dict


@dataclass(frozen=True)
class InstrumentSpec:
    """
    One instrument's CFD contract specification.

    contract_size       units of the underlying per 1.0 lot
                        (forex 100,000; gold 100 oz; silver 5,000 oz;
                         oil 1,000 bbl; index 1 → "currency per point")
    point_size          price value of one point / pip
                        (EURUSD 0.0001; JPY pairs 0.01; gold 0.01;
                         index 1.0)
    spread_points       typical dealing spread, expressed in points
                        (spread in price = spread_points × point_size)
    commission_per_lot  round-turn commission per lot, in quote currency
    commission_pct      commission as a fraction of notional, charged per side
                        (e.g. 0.0001 = 1 bp); applied on open AND close
    overnight_fee_long  daily financing as a fraction of notional for LONGS
                        (positive = debit you pay, negative = credit you receive)
    overnight_fee_short daily financing as a fraction of notional for SHORTS
    quote_currency      currency the instrument is quoted in
    """
    symbol:              str
    asset_class:         str
    contract_size:       float
    point_size:          float
    spread_points:       float
    commission_per_lot:  float = 0.0
    commission_pct:      float = 0.0
    overnight_fee_long:  float = 0.0
    overnight_fee_short: float = 0.0
    quote_currency:      str   = "USD"


# ─────────────────────────────────────────────────────────────────────────────
# Default (ILLUSTRATIVE) specs — tune to your broker
# ─────────────────────────────────────────────────────────────────────────────

_FOREX_TEMPLATE = InstrumentSpec(
    symbol="FOREX", asset_class="forex",
    contract_size=100_000, point_size=0.0001, spread_points=1.0,
    overnight_fee_long=0.00003, overnight_fee_short=0.00003,   # placeholder swap
    quote_currency="USD",
)

DEFAULT_SPECS: Dict[str, InstrumentSpec] = {
    # ── forex majors (1 lot = 100,000 units of base ccy) ─────────────────────
    "EURUSD": replace(_FOREX_TEMPLATE, symbol="EURUSD", spread_points=0.6),
    "GBPUSD": replace(_FOREX_TEMPLATE, symbol="GBPUSD", spread_points=0.9),
    "AUDUSD": replace(_FOREX_TEMPLATE, symbol="AUDUSD", spread_points=0.7),
    "NZDUSD": replace(_FOREX_TEMPLATE, symbol="NZDUSD", spread_points=1.2),
    "USDCAD": replace(_FOREX_TEMPLATE, symbol="USDCAD", spread_points=1.2, quote_currency="CAD"),
    "USDCHF": replace(_FOREX_TEMPLATE, symbol="USDCHF", spread_points=1.2, quote_currency="CHF"),
    "USDJPY": replace(_FOREX_TEMPLATE, symbol="USDJPY", spread_points=0.8, point_size=0.01, quote_currency="JPY"),
    "EURGBP": replace(_FOREX_TEMPLATE, symbol="EURGBP", spread_points=1.0, quote_currency="GBP"),
    "EURJPY": replace(_FOREX_TEMPLATE, symbol="EURJPY", spread_points=1.5, point_size=0.01, quote_currency="JPY"),

    # ── commodities ──────────────────────────────────────────────────────────
    "XAUUSD": InstrumentSpec("XAUUSD", "commodity", contract_size=100,  point_size=0.01,
                             spread_points=25, overnight_fee_long=0.00015, overnight_fee_short=-0.00005),
    "XAGUSD": InstrumentSpec("XAGUSD", "commodity", contract_size=5000, point_size=0.001,
                             spread_points=20, overnight_fee_long=0.00015, overnight_fee_short=-0.00005),
    "USOIL":  InstrumentSpec("USOIL",  "commodity", contract_size=1000, point_size=0.01,
                             spread_points=3,  overnight_fee_long=0.00020, overnight_fee_short=-0.00010),
    "UKOIL":  InstrumentSpec("UKOIL",  "commodity", contract_size=1000, point_size=0.01,
                             spread_points=3,  overnight_fee_long=0.00020, overnight_fee_short=-0.00010),

    # ── indices (1 lot = 1 currency unit per index point) ────────────────────
    "NAS100": InstrumentSpec("NAS100", "index", contract_size=1, point_size=1.0,
                             spread_points=1.0, overnight_fee_long=0.00020, overnight_fee_short=-0.00005),
    "SPX500": InstrumentSpec("SPX500", "index", contract_size=1, point_size=1.0,
                             spread_points=0.5, overnight_fee_long=0.00020, overnight_fee_short=-0.00005),
    "US30":   InstrumentSpec("US30",   "index", contract_size=1, point_size=1.0,
                             spread_points=2.0, overnight_fee_long=0.00020, overnight_fee_short=-0.00005),
    "GER40":  InstrumentSpec("GER40",  "index", contract_size=1, point_size=1.0,
                             spread_points=1.0, overnight_fee_long=0.00018, overnight_fee_short=-0.00005,
                             quote_currency="EUR"),
}

# common broker aliases → canonical key
_ALIASES: Dict[str, str] = {
    "GOLD": "XAUUSD", "XAU": "XAUUSD",
    "SILVER": "XAGUSD", "XAG": "XAGUSD",
    "OIL": "USOIL", "WTI": "USOIL", "CRUDE": "USOIL", "USCRUDE": "USOIL", "CL": "USOIL",
    "BRENT": "UKOIL", "BRENTOIL": "UKOIL",
    "NASDAQ": "NAS100", "NASDAQ100": "NAS100", "USTEC": "NAS100", "NDX": "NAS100", "US100": "NAS100",
    "SP500": "SPX500", "SPX": "SPX500", "US500": "SPX500", "SANDP500": "SPX500", "SP": "SPX500",
    "DOW": "US30", "DJI": "US30", "DJIA": "US30", "WALLSTREET": "US30", "US30CASH": "US30",
    "DAX": "GER40", "GER30": "GER40", "DE40": "GER40",
}
