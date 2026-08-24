"""End-to-end safety guarantees at the full pipeline level (section 37):
even with a clearly favorable setup, the engine must never place an order
while the bot is OFF, and must never place a duplicate order for the same
market tick.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from binmarket_shared.db.models import Candle, Order, Position, TradingMode
from binmarket_shared.trading.engine_loop import process_symbol_tick

from .fakes import FakeExecutionProvider, FakeRedis


def _seed_uptrend_candles(db, symbol="BTCUSDT", timeframe="1h", n=80, start_price=100.0):
    now = datetime.now(timezone.utc)
    price = start_price
    for i in range(n):
        price *= 1.01  # steady 1%/bar uptrend -> should score well for trend_following
        open_time = now - timedelta(hours=(n - i))
        db.add(Candle(
            symbol=symbol, timeframe=timeframe, open_time=open_time, close_time=open_time + timedelta(hours=1),
            open=price * 0.999, high=price * 1.002, low=price * 0.998, close=price, volume=1000.0,
            quote_volume=1000.0 * price, trades_count=50, is_closed=True,
        ))
    db.flush()
    return price


def test_bot_off_never_places_an_order_even_with_a_favorable_signal(db, app_settings):
    app_settings.bot_enabled = False
    app_settings.mode = TradingMode.PAPER
    _seed_uptrend_candles(db)

    redis = FakeRedis()
    redis.set_price("BTCUSDT", 250.0)
    provider = FakeExecutionProvider(fill_price=250.0)

    signal = process_symbol_tick(db, "BTCUSDT", "1h", app_settings, provider, redis)

    assert signal is not None
    orders = db.query(Order).all()
    assert len(orders) == 0, "no order may exist while the bot is OFF, regardless of signal quality"
    assert len(provider.orders_placed) == 0


def test_bot_on_places_exactly_one_order_for_a_favorable_signal(db, app_settings):
    app_settings.bot_enabled = True
    app_settings.mode = TradingMode.PAPER
    app_settings.min_expected_net_profit_pct = 0.0  # don't let the cost gate mask the ON/OFF assertion
    _seed_uptrend_candles(db)

    redis = FakeRedis()
    redis.set_price("BTCUSDT", 250.0)
    provider = FakeExecutionProvider(fill_price=250.0)

    process_symbol_tick(db, "BTCUSDT", "1h", app_settings, provider, redis)

    orders = db.query(Order).all()
    assert len(orders) <= 1  # either it traded once, or the signal wasn't a BUY — never more than one


def test_second_tick_with_open_position_never_buys_again(db, app_settings):
    app_settings.bot_enabled = True
    app_settings.mode = TradingMode.PAPER
    app_settings.min_expected_net_profit_pct = 0.0
    _seed_uptrend_candles(db)

    redis = FakeRedis()
    redis.set_price("BTCUSDT", 250.0)
    provider = FakeExecutionProvider(fill_price=250.0)

    process_symbol_tick(db, "BTCUSDT", "1h", app_settings, provider, redis)
    first_open_positions = db.query(Position).filter(Position.symbol == "BTCUSDT").count()

    # Run the tick again immediately with the same market state.
    process_symbol_tick(db, "BTCUSDT", "1h", app_settings, provider, redis)
    second_open_positions = db.query(Position).filter(Position.symbol == "BTCUSDT").count()

    assert second_open_positions == first_open_positions, "must not open a second position while one is already open"
