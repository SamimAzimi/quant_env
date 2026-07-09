"""Tests for libs.cfd_cost — spec resolution and the cost/P&L math."""
import pandas as pd
import pytest

from libs.cfd_cost import CFDCostModel, get_spec
from config.config import DEFAULT_SPECS


# ── spec resolution ──────────────────────────────────────────────────────────

def test_get_spec_direct_and_case_insensitive():
    assert get_spec("EURUSD") is DEFAULT_SPECS["EURUSD"]
    assert get_spec("eur/usd") is DEFAULT_SPECS["EURUSD"]
    assert get_spec("nas 100") is DEFAULT_SPECS["NAS100"]


def test_get_spec_aliases():
    assert get_spec("GOLD") is DEFAULT_SPECS["XAUUSD"]
    assert get_spec("WTI") is DEFAULT_SPECS["USOIL"]
    assert get_spec("DAX") is DEFAULT_SPECS["GER40"]


def test_get_spec_unknown_fx_pair_falls_back_to_template():
    spec = get_spec("SEKNOK")
    assert spec.symbol == "SEKNOK"
    assert spec.asset_class == "forex"
    assert spec.point_size == 0.0001
    assert spec.quote_currency == "NOK"


def test_get_spec_unknown_jpy_pair_gets_jpy_point_size():
    spec = get_spec("CADJPY")
    assert spec.point_size == 0.01
    assert spec.quote_currency == "JPY"


def test_get_spec_unknown_symbol_raises():
    with pytest.raises(KeyError):
        get_spec("NOT_A_SYMBOL_123")


# ── cost model math ──────────────────────────────────────────────────────────

@pytest.fixture
def demo_trades():
    return pd.DataFrame([
        # winning long held 2 nights
        {"trade_id": "T1", "side": "long",
         "entry_time": pd.Timestamp("2024-01-01 12:00"), "entry_price": 100.0,
         "exit_time":  pd.Timestamp("2024-01-03 15:00"), "exit_price": 103.0},
        # losing short, intraday (0 nights)
        {"trade_id": "T2", "side": "short",
         "entry_time": pd.Timestamp("2024-01-04 10:00"), "entry_price": 102.0,
         "exit_time":  pd.Timestamp("2024-01-04 16:00"), "exit_price": 103.0},
        # invalidated setup — never filled, must cost nothing
        {"trade_id": "T3", "side": "long",
         "entry_time": None, "entry_price": None,
         "exit_time":  pd.Timestamp("2024-01-05 11:00"), "exit_price": None},
    ])


def test_nas100_costs_and_pnl(demo_trades):
    # NAS100 spec: contract_size=1, point_size=1.0, spread_points=1.0,
    # no commission, financing long 0.0002 / short -0.00005 per night
    model = CFDCostModel("NAS100", lots=1.0)
    costed = model.add_costs(demo_trades).set_index("trade_id")

    long_ = costed.loc["T1"]
    assert long_["units"] == 1.0
    assert long_["notional"] == 100.0
    assert long_["nights_held"] == 2
    assert long_["spread_cost"] == pytest.approx(1.0)
    assert long_["commission_cost"] == pytest.approx(0.0)
    assert long_["financing_cost"] == pytest.approx(100.0 * 0.0002 * 2)
    assert long_["gross_pnl"] == pytest.approx(3.0)
    assert long_["net_pnl"] == pytest.approx(3.0 - 1.0 - 0.04)

    short = costed.loc["T2"]
    assert short["nights_held"] == 0
    assert short["gross_pnl"] == pytest.approx(-1.0)     # short loses on rise
    assert short["financing_cost"] == pytest.approx(0.0)
    assert short["net_pnl"] == pytest.approx(-2.0)       # -1 gross - 1 spread


def test_unfilled_setup_costs_nothing(demo_trades):
    costed = CFDCostModel("NAS100", lots=1.0).add_costs(demo_trades).set_index("trade_id")
    inval = costed.loc["T3"]
    assert inval["spread_cost"] == 0.0
    assert inval["commission_cost"] == 0.0
    assert inval["financing_cost"] == 0.0
    assert pd.isna(inval["gross_pnl"]) and pd.isna(inval["net_pnl"])


def test_lots_scale_units_and_costs(demo_trades):
    one = CFDCostModel("NAS100", lots=1.0).add_costs(demo_trades)
    two = CFDCostModel("NAS100", lots=2.0).add_costs(demo_trades)
    filled = one["net_pnl"].notna()
    assert (two.loc[filled, "units"] == 2 * one.loc[filled, "units"]).all()
    assert (two.loc[filled, "spread_cost"] == 2 * one.loc[filled, "spread_cost"]).all()
    assert (two.loc[filled, "gross_pnl"] == 2 * one.loc[filled, "gross_pnl"]).all()


def test_fx_rate_converts_to_account_currency(demo_trades):
    fx = 0.5
    base = CFDCostModel("NAS100", lots=1.0).add_costs(demo_trades)
    conv = CFDCostModel("NAS100", lots=1.0, fx_rate=fx).add_costs(demo_trades)
    filled = base["net_pnl"].notna()
    assert conv.loc[filled, "total_cost"].tolist() == pytest.approx(
        (base.loc[filled, "total_cost"] * fx).tolist())
    assert conv.loc[filled, "gross_pnl"].tolist() == pytest.approx(
        (base.loc[filled, "gross_pnl"] * fx).tolist())


def test_spec_overrides_apply():
    model = CFDCostModel("NAS100", spread_points=4.0, commission_per_lot=7.0)
    assert model.spec.spread_points == 4.0
    assert model.spec.commission_per_lot == 7.0
    # untouched fields keep the default spec values
    assert model.spec.contract_size == DEFAULT_SPECS["NAS100"].contract_size


def test_empty_frame_gets_cost_columns():
    empty = pd.DataFrame(columns=["side", "entry_price", "exit_price"])
    costed = CFDCostModel("EURUSD").add_costs(empty)
    for col in CFDCostModel.COST_COLUMNS:
        assert col in costed.columns
    assert len(costed) == 0


def test_summary_aggregates(demo_trades):
    model = CFDCostModel("NAS100", lots=1.0)
    summary = model.summary(model.add_costs(demo_trades))
    assert summary["trades"] == 2                       # invalidation excluded
    assert summary["gross_pnl"] == pytest.approx(2.0)   # +3 - 1
    assert summary["net_pnl"] == pytest.approx(
        summary["gross_pnl"] - summary["total_cost"])
