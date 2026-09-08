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


def test_position_rejected_when_one_lot_step_below_would_miss_min_notional():
    """Regression test for a real production bug: a position sized to just
    clear min_notional (e.g. $5.56 against a $5 minimum) gets bought fine,
    but closing it later floors to one LOT_SIZE step lower (after
    commission-netting), which can drop it under min_notional with no valid
    sell quantity in between - the position becomes permanently unsellable
    through a normal order. Must be rejected at sizing time instead.
    """
    # step_size 0.00001, entry $79,500 -> one step is worth ~$0.795.
    # max_position_size_pct is tuned so the pre-round position value lands
    # at exactly $5.9625 -> rounds down to 0.00007 ($5.565, clears the $5
    # minimum), but one step below that (0.00006, $4.77) does not.
    filters = SymbolFilters(
        symbol="BTCUSDT", tick_size=0.01, step_size=0.00001, min_qty=0.00001, max_qty=1000, min_notional=5.0,
    )
    result = calculate_position_size(
        available_capital=1_000, risk_per_trade_pct=50.0, entry_price=79_500, stop_loss_price=78_000,
        current_total_exposure_value=0, max_total_exposure_pct=100, max_position_size_pct=0.59625,
        symbol_filters=filters,
    )
    assert not result.is_tradeable
    assert "min_notional" in (result.rejection_reason or "")


def test_position_accepted_with_enough_margin_above_min_notional():
    # Same filters, but sized comfortably above min_notional (~$11.9) so
    # even one step down at close time (~$11.1) stays well clear of it.
    filters = SymbolFilters(
        symbol="BTCUSDT", tick_size=0.01, step_size=0.00001, min_qty=0.00001, max_qty=1000, min_notional=5.0,
    )
    result = calculate_position_size(
        available_capital=1_000, risk_per_trade_pct=50.0, entry_price=79_500, stop_loss_price=78_000,
        current_total_exposure_value=0, max_total_exposure_pct=100, max_position_size_pct=1.2,
        symbol_filters=filters,
    )
    assert result.is_tradeable
    assert (result.quantity - filters.step_size) * 79_500 >= filters.min_notional


def test_position_rejected_when_stop_loss_price_would_miss_min_notional_even_if_entry_price_passes():
    """Regression test for a real live incident: a CHIPUSDT scalping position
    (step_size=1, tight ~0.6% stop typical of scalping) was sized to 128
    units at $0.03938 - one step down (127) priced at ENTRY was $5.00126,
    just barely clearing the $5 minimum, so the old entry-price-only check
    let it through. The position was actually meant to be sellable down to
    its stop-loss price (~0.6% lower), where 127 units was worth only
    $4.97 - under the minimum, with no valid quantity to sell. The
    stop-loss fired, every close attempt was rejected (-1013 NOTIONAL), and
    the loss grew uncapped every cycle instead of being cut. The check must
    use the stop-loss price, not the entry price.
    """
    filters = SymbolFilters(
        symbol="CHIPUSDT", tick_size=0.00001, step_size=1.0, min_qty=1.0, max_qty=913_205_152, min_notional=5.0,
    )
    result = calculate_position_size(
        available_capital=1_000, risk_per_trade_pct=50.0, entry_price=0.03938, stop_loss_price=0.03914372,
        current_total_exposure_value=0, max_total_exposure_pct=100, max_position_size_pct=0.505,
        symbol_filters=filters,
    )
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
