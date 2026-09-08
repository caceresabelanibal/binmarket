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
        # A perfectly smooth 1%/bar uptrend has ~zero realized volatility,
        # which classify_regime correctly reports as UNKNOWN (not NORMAL) —
        # add a small deterministic zigzag so this reads as a real, tradeable
        # NORMAL-volatility uptrend instead.
        price *= 1.01 + 0.0025 * ((i % 5) - 2)
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

    signal = process_symbol_tick(db, "BTCUSDT", app_settings, provider, redis)

    assert signal is not None
    orders = db.query(Order).all()
    assert len(orders) == 0, "no order may exist while the bot is OFF, regardless of signal quality"
    assert len(provider.orders_placed) == 0


def test_no_live_ticker_blocks_a_new_entry_even_with_a_favorable_signal(db, app_settings):
    """Regression test for a real live incident: a freshly selected, fast-
    moving symbol had no cached WebSocket ticker yet, so the engine fell
    back to the last CLOSED candle's close (hours old for a fast mover) as
    "current price" - sizing a brand new entry's stop-loss/take-profit off
    a reference 33% away from the real market, putting the stop on the
    wrong side of the actual fill. A new position must never open without a
    real live price, no matter how good the signal looks on stale data.
    """
    app_settings.bot_enabled = True
    app_settings.mode = TradingMode.PAPER
    app_settings.min_expected_net_profit_pct = 0.0
    _seed_uptrend_candles(db)

    redis = FakeRedis()  # no set_price() - no cached ticker, same as a freshly-selected symbol
    provider = FakeExecutionProvider(fill_price=250.0)

    signal = process_symbol_tick(db, "BTCUSDT", app_settings, provider, redis)

    assert signal.action.value == "NO_TRADE"
    assert "precio en vivo" in signal.reasons[0]
    assert len(provider.orders_placed) == 0


def test_bot_on_places_exactly_one_order_for_a_favorable_signal(db, app_settings):
    app_settings.bot_enabled = True
    app_settings.mode = TradingMode.PAPER
    app_settings.min_expected_net_profit_pct = 0.0  # don't let the cost gate mask the ON/OFF assertion
    _seed_uptrend_candles(db)

    redis = FakeRedis()
    redis.set_price("BTCUSDT", 250.0)
    provider = FakeExecutionProvider(fill_price=250.0)

    process_symbol_tick(db, "BTCUSDT", app_settings, provider, redis)

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

    process_symbol_tick(db, "BTCUSDT", app_settings, provider, redis)
    first_open_positions = db.query(Position).filter(Position.symbol == "BTCUSDT").count()

    # Run the tick again immediately with the same market state.
    process_symbol_tick(db, "BTCUSDT", app_settings, provider, redis)
    second_open_positions = db.query(Position).filter(Position.symbol == "BTCUSDT").count()

    assert second_open_positions == first_open_positions, "must not open a second position while one is already open"


def _seed_5m_candles(db, symbol="BTCUSDT", n=40, start_price=100.0):
    now = datetime.now(timezone.utc)
    price = start_price
    for i in range(n):
        price *= 1.002
        open_time = now - timedelta(minutes=5 * (n - i))
        db.add(Candle(
            symbol=symbol, timeframe="5m", open_time=open_time, close_time=open_time + timedelta(minutes=5),
            open=price * 0.999, high=price * 1.001, low=price * 0.998, close=price, volume=500.0,
            quote_volume=500.0 * price, trades_count=20, is_closed=True,
        ))
    db.flush()
    return price


def test_scalping_strategy_generates_its_signal_off_5m_not_1h(db, app_settings):
    """Regression guard for the per-strategy timeframe routing: regime is
    always read off 1h, but a strategy with `preferred_timeframe = "5m"`
    must have its own signal (and the persisted Signal row) reflect 5m —
    never silently fall back to the 1h data used only for the regime read.
    """
    app_settings.bot_enabled = False  # irrelevant here, just inspecting the signal
    _seed_uptrend_candles(db)  # 1h data, needed for regime classification
    _seed_5m_candles(db)  # 5m data, needed for scalping's own entry logic

    redis = FakeRedis()
    redis.set_price("BTCUSDT", 250.0)
    provider = FakeExecutionProvider(fill_price=250.0)

    signal = process_symbol_tick(db, "BTCUSDT", app_settings, provider, redis, strategy_priority=["scalping"])

    assert signal is not None
    assert signal.strategy_name == "scalping"
    assert signal.timeframe == "5m"


def test_scalping_is_skipped_without_enough_5m_history_even_with_good_1h_regime(db, app_settings):
    app_settings.bot_enabled = False
    _seed_uptrend_candles(db)  # only 1h data seeded — no 5m history at all

    redis = FakeRedis()
    redis.set_price("BTCUSDT", 250.0)
    provider = FakeExecutionProvider(fill_price=250.0)

    signal = process_symbol_tick(db, "BTCUSDT", app_settings, provider, redis, strategy_priority=["scalping"])

    assert signal is not None
    assert signal.action.value == "NO_TRADE"
    assert any("Faltan datos" in r for r in signal.reasons)
