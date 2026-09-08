from __future__ import annotations

import pytest

from binmarket_shared.db.models import Position, PositionStatus, Signal, SignalAction, Symbol, TradingMode
from binmarket_shared.trading.orders.manager import OrderManager

from .fakes import FakeExecutionProvider


def _signal(db, symbol="BTCUSDT", suggested_entry_price=None, suggested_stop_loss=95, suggested_take_profit=110):
    s = Signal(
        symbol=symbol, timeframe="1h", strategy_name="trend_following", action=SignalAction.BUY,
        reasons=["test"], suggested_entry_price=suggested_entry_price,
        suggested_stop_loss=suggested_stop_loss, suggested_take_profit=suggested_take_profit,
    )
    db.add(s)
    db.flush()
    return s


def test_open_position_creates_order_and_position(db):
    provider = FakeExecutionProvider(fill_price=100.0)
    om = OrderManager(db, provider)
    signal = _signal(db)

    order, position = om.open_position_from_signal(signal, quantity=1.0, mode=TradingMode.PAPER)

    assert order.status.value == "FILLED"
    assert position is not None
    assert position.entry_price == 100.0
    assert position.status == PositionStatus.OPEN
    assert len(provider.orders_placed) == 1


def test_duplicate_signal_does_not_place_a_second_order(db):
    """The core idempotency guarantee from section 18/37: retrying the same
    signal (e.g. after a crash/restart) must never double-buy."""
    provider = FakeExecutionProvider(fill_price=100.0)
    om = OrderManager(db, provider)
    signal = _signal(db)

    order1, _ = om.open_position_from_signal(signal, quantity=1.0, mode=TradingMode.PAPER)
    order2, _ = om.open_position_from_signal(signal, quantity=1.0, mode=TradingMode.PAPER)

    assert order1.id == order2.id
    assert len(provider.orders_placed) == 1  # NOT 2


def test_position_quantity_nets_out_commission_paid_in_the_base_asset(db):
    """Regression test for a real production bug: Binance often deducts the
    trading fee from the asset you just bought (e.g. BTC on a BTCUSDT BUY),
    so the account ends up holding strictly less than `filled_quantity`.
    Storing the gross amount made the position impossible to close later —
    Binance rejected the SELL with "insufficient balance" (code -2010).
    """
    db.add(Symbol(symbol="BTCUSDT", base_asset="BTC", quote_asset="USDT"))
    db.flush()

    provider = FakeExecutionProvider(fill_price=80_000.0, commission_asset="BTC")
    om = OrderManager(db, provider)
    signal = _signal(db)

    order, position = om.open_position_from_signal(signal, quantity=0.00008, mode=TradingMode.PAPER)

    expected_commission = 0.00008 * 0.001
    assert position.quantity == 0.00008 - expected_commission
    assert position.quantity < 0.00008  # never store more than what's actually held


def test_position_quantity_not_reduced_when_commission_paid_in_quote_asset(db):
    db.add(Symbol(symbol="BTCUSDT", base_asset="BTC", quote_asset="USDT"))
    db.flush()

    provider = FakeExecutionProvider(fill_price=80_000.0, commission_asset="USDT")
    om = OrderManager(db, provider)
    signal = _signal(db)

    _, position = om.open_position_from_signal(signal, quantity=0.00008, mode=TradingMode.PAPER)

    assert position.quantity == 0.00008  # fee came out of USDT, BTC balance is untouched


def test_failed_fill_does_not_create_a_position(db):
    provider = FakeExecutionProvider(should_fail=True)
    om = OrderManager(db, provider)
    signal = _signal(db)

    order, position = om.open_position_from_signal(signal, quantity=1.0, mode=TradingMode.PAPER)

    assert order.status.value == "REJECTED"
    assert position is None


def test_stop_loss_reanchors_to_the_real_fill_price_not_the_stale_estimate(db):
    """Regression test for a real live incident: TUTUSDT's signal computed
    stop_loss=0.05377/take_profit=0.07726 relative to a stale reference
    price of 0.06048 (a freshly auto-selected, fast-moving micro-cap whose
    cached ticker/candle reference hadn't caught up to the real market). The
    actual fill landed at 0.04067 - 33% away - so the stop-loss, taken
    verbatim as an absolute price, ended up *above* the real entry price.
    The position's own monitoring saw current_price <= stop_loss as true
    from the very first tick and closed it 17 seconds after opening.
    Stop-loss/take-profit must be re-anchored to the real fill price,
    preserving the strategy's intended relative distance instead of
    trusting an absolute level computed off a price that was never real.
    """
    signal = _signal(
        db, symbol="TUTUSDT",
        suggested_entry_price=0.06048, suggested_stop_loss=0.05376938465674572,
        suggested_take_profit=0.0772565383581357,
    )
    # Real fill lands 33% below the stale reference used to size the signal.
    provider = FakeExecutionProvider(fill_price=0.04067)
    om = OrderManager(db, provider)

    _, position = om.open_position_from_signal(signal, quantity=1.0, mode=TradingMode.PAPER)

    assert position.entry_price == 0.04067
    assert position.stop_loss < position.entry_price  # never on the wrong side, whatever the estimate said
    assert position.take_profit > position.entry_price

    # Same relative stop/reward distance the signal intended, just
    # re-anchored to the real entry instead of the stale reference.
    stale_ref = 0.06048
    stop_distance_pct = (stale_ref - 0.05376938465674572) / stale_ref
    reward_distance_pct = (0.0772565383581357 - stale_ref) / stale_ref
    assert position.stop_loss == pytest.approx(0.04067 * (1 - stop_distance_pct))
    assert position.take_profit == pytest.approx(0.04067 * (1 + reward_distance_pct))


def test_close_position_computes_pnl_net_of_both_legs_commission(db):
    entry_provider = FakeExecutionProvider(fill_price=100.0)
    om = OrderManager(db, entry_provider)
    signal = _signal(db)
    opening_order, position = om.open_position_from_signal(signal, quantity=1.0, mode=TradingMode.PAPER)
    entry_commission = opening_order.commission_total

    exit_provider = FakeExecutionProvider(fill_price=110.0)
    om_exit = OrderManager(db, exit_provider)
    closing_order = om_exit.close_position(position, "take profit", TradingMode.PAPER)

    assert position.status == PositionStatus.CLOSED
    expected_pnl = (110.0 - 100.0) * 1.0 - entry_commission - closing_order.commission_total
    assert position.realized_pnl == expected_pnl


def test_closing_the_same_position_twice_is_a_no_op_second_time(db):
    provider = FakeExecutionProvider(fill_price=100.0)
    om = OrderManager(db, provider)
    signal = _signal(db)
    _, position = om.open_position_from_signal(signal, quantity=1.0, mode=TradingMode.PAPER)

    order1 = om.close_position(position, "reason", TradingMode.PAPER)
    order2 = om.close_position(position, "reason", TradingMode.PAPER)

    assert order1.id == order2.id
    # only 2 total calls to the provider: one open, one close (not two closes)
    assert len(provider.orders_placed) == 2


def test_a_rejected_close_attempt_is_retried_not_permanently_stuck(db):
    """Regression test for a real production bug: the close-order
    client_order_id is deterministic per *position*, so once a close attempt
    got REJECTED by Binance (e.g. a momentary balance mismatch), every
    subsequent call - an automated retry, or a manual "sell now" click days
    later - silently returned that same stale REJECTED order without ever
    calling Binance again. A stop-loss that failed to execute once stayed
    permanently unable to close, which defeats capital preservation. A
    REJECTED order never touched the exchange, so retrying it is always safe.
    """
    open_provider = FakeExecutionProvider(fill_price=100.0)
    om_open = OrderManager(db, open_provider)
    signal = _signal(db)
    _, position = om_open.open_position_from_signal(signal, quantity=1.0, mode=TradingMode.PAPER)

    failing_provider = FakeExecutionProvider(should_fail=True)
    om_fail = OrderManager(db, failing_provider)
    rejected_order = om_fail.close_position(position, "stop-loss", TradingMode.PAPER)
    assert rejected_order.status.value == "REJECTED"
    assert position.status == PositionStatus.OPEN  # never actually closed

    recovered_provider = FakeExecutionProvider(fill_price=90.0)
    om_retry = OrderManager(db, recovered_provider)
    retried_order = om_retry.close_position(position, "stop-loss (retry)", TradingMode.PAPER)

    assert retried_order.id != rejected_order.id
    assert retried_order.status.value == "FILLED"
    assert position.status == PositionStatus.CLOSED
    assert len(recovered_provider.orders_placed) == 1  # the retry actually hit the provider


def test_close_position_converts_base_asset_opening_commission_to_quote_terms(db):
    """Regression test for a real production bug found live: when the BUY's
    commission is paid in the base asset (the common case, no BNB discount),
    Order.commission_total is stored in that base asset's units - but
    close_position() was subtracting it from realized_pnl as if it were
    already in USDT. On a real CHIPUSDT trade this treated a "0.131 CHIP"
    fee as "0.131 USDT" (~25x too much for a ~$0.0388 coin), turning an
    actually-profitable take-profit exit into a reported loss.
    """
    db.add(Symbol(symbol="CHIPUSDT", base_asset="CHIP", quote_asset="USDT", lot_step_size=1.0))
    db.flush()

    open_provider = FakeExecutionProvider(fill_price=0.03879, commission_asset="CHIP")
    om_open = OrderManager(db, open_provider)
    signal = _signal(db, symbol="CHIPUSDT")
    opening_order, position = om_open.open_position_from_signal(signal, quantity=131.0, mode=TradingMode.LIVE)
    assert opening_order.commission_asset == "CHIP"
    assert opening_order.commission_total == pytest.approx(0.131)  # 131 * 0.001, in CHIP

    close_provider = FakeExecutionProvider(fill_price=0.03916, commission_asset="USDT")
    om_close = OrderManager(db, close_provider)
    order = om_close.close_position(position, "take profit", TradingMode.LIVE)

    # Raw price move (0.03916 - 0.03879) * 130 sold = 0.0481, minus the
    # opening fee correctly valued in USDT (0.131 CHIP * 0.03879 ~= 0.00508)
    # minus the closing fee (already USDT, 130 * 0.03916 * 0.001 ~= 0.00509)
    # - a small net gain, not the loss the bug reported.
    expected_opening_fee_usdt = 0.131 * 0.03879
    expected_closing_fee_usdt = 130 * 0.03916 * 0.001
    expected_pnl = (0.03916 - 0.03879) * 130 - expected_opening_fee_usdt - expected_closing_fee_usdt

    assert order.status.value == "FILLED"
    assert position.realized_pnl > 0
    assert position.realized_pnl == pytest.approx(expected_pnl, abs=1e-6)


def test_close_position_sweeps_in_leftover_same_symbol_dust_to_clear_min_notional(db):
    """Regression test for a real live incident: a stop-loss kept retrying
    every ~15s for over an hour, always rejected with NOTIONAL, because the
    position's own tracked quantity (0.00006993 BTC), floored to the lot
    step, was worth just under Binance's $5 minimum at the falling price.
    The real account balance was actually 0.00007985 BTC - dust left over
    from a *previous* BTCUSDT position that hit the exact same trap when it
    closed. Since only one position per symbol is ever open at a time, that
    leftover dust isn't "someone else's" - sweeping it in clears $5 and
    actually closes the position instead of leaving the stop-loss stuck
    forever.
    """
    db.add(Symbol(symbol="BTCUSDT", base_asset="BTC", quote_asset="USDT", lot_step_size=0.00001, min_notional=5.0))
    db.flush()

    open_provider = FakeExecutionProvider(fill_price=79318.82, commission_asset="USDT")
    om_open = OrderManager(db, open_provider)
    signal = _signal(db, symbol="BTCUSDT")
    _, position = om_open.open_position_from_signal(signal, quantity=0.00006993, mode=TradingMode.LIVE)

    # Falling price: 0.00006 BTC (one floor below tracked quantity) is worth
    # under $5, but the real held balance (0.00007985, including old dust)
    # floors to 0.00007, worth $5.46 - just enough.
    close_provider = FakeExecutionProvider(
        fill_price=77956.50, commission_asset="USDT", base_asset_balance=0.00007985,
    )
    om_close = OrderManager(db, close_provider)
    order = om_close.close_position(position, "Stop-loss alcanzado", TradingMode.LIVE)

    assert len(close_provider.orders_placed) == 1
    _, _, placed_quantity = close_provider.orders_placed[0]
    assert placed_quantity == pytest.approx(0.00007)
    assert order.status.value == "FILLED"
    assert position.status == PositionStatus.CLOSED


def test_close_position_never_sweeps_dust_in_paper_mode(db):
    # PaperExecutionProvider's balance is a simulated USDT figure regardless
    # of which asset is asked for - sweeping based on it would be nonsense.
    db.add(Symbol(symbol="BTCUSDT", base_asset="BTC", quote_asset="USDT", lot_step_size=0.00001, min_notional=5.0))
    db.flush()

    open_provider = FakeExecutionProvider(fill_price=79318.82, commission_asset="USDT")
    om_open = OrderManager(db, open_provider)
    signal = _signal(db, symbol="BTCUSDT")
    _, position = om_open.open_position_from_signal(signal, quantity=0.00006993, mode=TradingMode.PAPER)

    close_provider = FakeExecutionProvider(
        fill_price=77956.50, commission_asset="USDT", base_asset_balance=0.00007985,
    )
    om_close = OrderManager(db, close_provider)
    om_close.close_position(position, "Stop-loss alcanzado", TradingMode.PAPER)

    _, _, placed_quantity = close_provider.orders_placed[0]
    assert placed_quantity == pytest.approx(0.00006)  # floored from the tracked quantity only, no sweep


def test_close_position_floors_sell_quantity_to_the_lot_size_step(db):
    """Regression test for a real production bug: netting out the base-asset
    commission (see test_position_quantity_nets_out_commission_paid_in_the_base_asset)
    leaves position.quantity as an exact-to-the-satoshi figure like
    0.00007992 BTC, which is honest about what's held but is not a multiple
    of BTCUSDT's real LOT_SIZE step (0.00001) - Binance rejects that SELL
    with "Filter failure: LOT_SIZE" (-1013). The close must floor to the
    step before placing the order.
    """
    db.add(Symbol(symbol="BTCUSDT", base_asset="BTC", quote_asset="USDT", lot_step_size=0.00001))
    db.flush()

    open_provider = FakeExecutionProvider(fill_price=80_000.0, commission_asset="BTC")
    om = OrderManager(db, open_provider)
    signal = _signal(db)
    _, position = om.open_position_from_signal(signal, quantity=0.00008, mode=TradingMode.PAPER)
    assert position.quantity == pytest.approx(0.00007992)  # exact, non-step-aligned amount actually held

    close_provider = FakeExecutionProvider(fill_price=81_000.0)
    om_close = OrderManager(db, close_provider)
    order = om_close.close_position(position, "take profit", TradingMode.PAPER)

    assert len(close_provider.orders_placed) == 1
    placed_symbol, placed_side, placed_quantity = close_provider.orders_placed[0]
    assert (placed_symbol, placed_side) == ("BTCUSDT", "SELL")
    assert placed_quantity == pytest.approx(0.00007)
    assert order.status.value == "FILLED"
    assert position.status == PositionStatus.CLOSED
