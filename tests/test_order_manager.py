from __future__ import annotations

from binmarket_shared.db.models import Position, PositionStatus, Signal, SignalAction, TradingMode
from binmarket_shared.trading.orders.manager import OrderManager

from .fakes import FakeExecutionProvider


def _signal(db, symbol="BTCUSDT"):
    s = Signal(
        symbol=symbol, timeframe="1h", strategy_name="trend_following", action=SignalAction.BUY,
        reasons=["test"], suggested_stop_loss=95, suggested_take_profit=110,
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


def test_failed_fill_does_not_create_a_position(db):
    provider = FakeExecutionProvider(should_fail=True)
    om = OrderManager(db, provider)
    signal = _signal(db)

    order, position = om.open_position_from_signal(signal, quantity=1.0, mode=TradingMode.PAPER)

    assert order.status.value == "REJECTED"
    assert position is None


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
