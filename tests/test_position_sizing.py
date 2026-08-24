import pytest

from binmarket_shared.binance.filters import SymbolFilters
from binmarket_shared.quant.position_sizing import calculate_position_size


def test_quantity_scales_with_risk_and_stop_distance():
    """Risking 1% of $10,000 with a $2 stop distance on a $100 entry should
    size to risk_amount / stop_distance = 100 / 2 = 50 units, unless capped."""
    result = calculate_position_size(
        available_capital=10_000, risk_per_trade_pct=1.0, entry_price=100, stop_loss_price=98,
        current_total_exposure_value=0, max_total_exposure_pct=100, max_position_size_pct=100,
    )
    assert result.is_tradeable
    assert result.quantity == pytest.approx(50, rel=0.01)


def test_position_capped_by_max_position_size_pct():
    result = calculate_position_size(
        available_capital=10_000, risk_per_trade_pct=1.0, entry_price=100, stop_loss_price=98,
        current_total_exposure_value=0, max_total_exposure_pct=100, max_position_size_pct=5,
    )
    assert result.position_value <= 10_000 * 0.05 + 1e-6
    assert any("max_position_size_pct" in n for n in result.notes)


def test_position_rejected_when_exposure_budget_exhausted():
    result = calculate_position_size(
        available_capital=10_000, risk_per_trade_pct=1.0, entry_price=100, stop_loss_price=98,
        current_total_exposure_value=5_000, max_total_exposure_pct=50, max_position_size_pct=100,
    )
    assert not result.is_tradeable
    assert result.quantity == 0.0


def test_position_rejected_on_invalid_stop_loss():
    result = calculate_position_size(
        available_capital=10_000, risk_per_trade_pct=1.0, entry_price=100, stop_loss_price=101,
        current_total_exposure_value=0, max_total_exposure_pct=100, max_position_size_pct=100,
    )
    assert not result.is_tradeable
    assert "invalid" in (result.rejection_reason or "")


def test_position_respects_binance_min_notional_filter():
    filters = SymbolFilters(symbol="BTCUSDT", tick_size=0.01, step_size=0.001, min_qty=0.001, max_qty=1000, min_notional=50_000)
    result = calculate_position_size(
        available_capital=1_000, risk_per_trade_pct=1.0, entry_price=30_000, stop_loss_price=29_500,
        current_total_exposure_value=0, max_total_exposure_pct=100, max_position_size_pct=100,
        symbol_filters=filters,
    )
    # $1,000 capital can never reach the $50,000 min_notional -> must reject, not silently round up
    assert not result.is_tradeable
    assert "min_notional" in (result.rejection_reason or "")


def test_position_rounds_quantity_to_lot_step_size():
    filters = SymbolFilters(symbol="BTCUSDT", tick_size=0.01, step_size=0.01, min_qty=0.01, max_qty=1000, min_notional=10)
    result = calculate_position_size(
        available_capital=100_000, risk_per_trade_pct=1.0, entry_price=100, stop_loss_price=98,
        current_total_exposure_value=0, max_total_exposure_pct=100, max_position_size_pct=100,
        symbol_filters=filters,
    )
    assert result.is_tradeable
    # quantity must be an exact multiple of the 0.01 step size
    assert round(result.quantity / 0.01) * 0.01 == pytest.approx(result.quantity)
