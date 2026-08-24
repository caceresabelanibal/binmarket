import pytest

from binmarket_shared.quant.costs import (
    apply_slippage,
    estimate_spread_pct,
    estimate_trade_economics,
    passes_profitability_gate,
)


def test_estimate_spread_pct_basic():
    assert estimate_spread_pct(99, 101) == pytest.approx(2.0, abs=0.01)


def test_estimate_spread_pct_handles_zero_prices():
    assert estimate_spread_pct(0, 0) == 0.0


def test_trade_economics_rejects_when_costs_exceed_gross_profit():
    """A tiny 0.3% target move can't survive 0.1% round-trip fees + spread +
    slippage on top of themselves — this is exactly the scenario section 13
    of the spec asks the system to catch (no naive 'buy low sell high')."""
    result = estimate_trade_economics(
        entry_price=100, take_profit_price=100.3, stop_loss_price=99.5,
        taker_fee_pct=0.1, spread_pct=0.05, slippage_pct=0.05,
    )
    assert result.net_profit_pct < 0.15
    assert not passes_profitability_gate(result, min_expected_net_profit_pct=0.15)


def test_trade_economics_accepts_when_target_clears_costs():
    result = estimate_trade_economics(
        entry_price=100, take_profit_price=105, stop_loss_price=98,
        taker_fee_pct=0.1, spread_pct=0.05, slippage_pct=0.05,
    )
    assert result.net_profit_pct > 4.0
    assert passes_profitability_gate(result, min_expected_net_profit_pct=0.15)
    assert result.risk_reward_ratio == pytest.approx(5 / 2, rel=0.01)


def test_apply_slippage_makes_buys_worse_and_sells_worse():
    buy_price = apply_slippage(100, "BUY", 0.5)
    sell_price = apply_slippage(100, "SELL", 0.5)
    assert buy_price > 100  # you pay more when buying
    assert sell_price < 100  # you receive less when selling
