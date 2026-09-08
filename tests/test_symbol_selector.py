from __future__ import annotations

from datetime import datetime, timedelta, timezone

from binmarket_shared.db.models import Position, PositionStatus, Signal, SignalAction, Symbol, TradingMode
from binmarket_shared.trading.symbol_selector import select_volatile_symbols


class FakeTickerClient:
    """Duck-typed stand-in for BinanceClient — select_volatile_symbols only
    ever calls `.get_ticker_24hr()` with no arguments."""

    def __init__(self, tickers: list[dict]):
        self._tickers = tickers

    def get_ticker_24hr(self):
        return self._tickers


def _symbol(db, symbol, quote="USDT", status="TRADING", is_auto=False, is_selected=False):
    row = Symbol(
        symbol=symbol, base_asset=symbol.replace(quote, ""), quote_asset=quote, status=status,
        is_auto_selected=is_auto, is_selected=is_selected,
    )
    db.add(row)
    db.flush()
    return row


def test_picks_the_most_volatile_liquid_usdt_pair(db):
    _symbol(db, "BTCUSDT")
    _symbol(db, "ETHUSDT")
    _symbol(db, "DOGEUSDT")

    client = FakeTickerClient([
        {"symbol": "BTCUSDT", "priceChangePercent": "1.0", "quoteVolume": "50000000"},
        {"symbol": "ETHUSDT", "priceChangePercent": "8.5", "quoteVolume": "40000000"},
        {"symbol": "DOGEUSDT", "priceChangePercent": "-6.0", "quoteVolume": "30000000"},
    ])

    chosen = select_volatile_symbols(db, client, max_symbols=1, min_volume_usdt=5_000_000)

    assert chosen == ["ETHUSDT"]  # 8.5% move beats -6.0% (abs) and 1.0%
    eth = db.query(Symbol).filter(Symbol.symbol == "ETHUSDT").one()
    assert eth.is_selected is True
    assert eth.is_auto_selected is True


def test_filters_out_illiquid_pairs_even_if_volatile(db):
    _symbol(db, "BTCUSDT")
    _symbol(db, "SHADYUSDT")

    client = FakeTickerClient([
        {"symbol": "BTCUSDT", "priceChangePercent": "1.0", "quoteVolume": "50000000"},
        {"symbol": "SHADYUSDT", "priceChangePercent": "40.0", "quoteVolume": "1000"},  # huge move, tiny volume
    ])

    chosen = select_volatile_symbols(db, client, max_symbols=2, min_volume_usdt=5_000_000)

    assert chosen == ["BTCUSDT"]  # SHADYUSDT excluded by the liquidity filter


def test_ignores_non_usdt_and_non_trading_pairs(db):
    _symbol(db, "BTCUSDT")
    _symbol(db, "BTCUSD", quote="USD")  # wrong quote asset for this system
    _symbol(db, "ETHUSDT", status="BREAK")  # not currently tradeable

    client = FakeTickerClient([
        {"symbol": "BTCUSDT", "priceChangePercent": "1.0", "quoteVolume": "50000000"},
        {"symbol": "BTCUSD", "priceChangePercent": "99.0", "quoteVolume": "50000000"},
        {"symbol": "ETHUSDT", "priceChangePercent": "50.0", "quoteVolume": "50000000"},
    ])

    chosen = select_volatile_symbols(db, client, max_symbols=5, min_volume_usdt=5_000_000)

    assert chosen == ["BTCUSDT"]


def test_never_touches_a_manually_selected_symbol(db):
    _symbol(db, "BTCUSDT", is_selected=True, is_auto=False)  # user picked this by hand
    _symbol(db, "ETHUSDT")

    client = FakeTickerClient([
        {"symbol": "BTCUSDT", "priceChangePercent": "0.1", "quoteVolume": "50000000"},
        {"symbol": "ETHUSDT", "priceChangePercent": "9.0", "quoteVolume": "50000000"},
    ])

    select_volatile_symbols(db, client, max_symbols=1, min_volume_usdt=5_000_000)

    btc = db.query(Symbol).filter(Symbol.symbol == "BTCUSDT").one()
    assert btc.is_selected is True  # untouched manual pick, even though it wasn't chosen this round
    assert btc.is_auto_selected is False


def test_revokes_previous_auto_selection_that_fell_out_of_the_ranking(db):
    _symbol(db, "DOGEUSDT", is_selected=True, is_auto=True)  # auto-picked last round
    _symbol(db, "ETHUSDT")

    client = FakeTickerClient([
        {"symbol": "DOGEUSDT", "priceChangePercent": "0.1", "quoteVolume": "50000000"},
        {"symbol": "ETHUSDT", "priceChangePercent": "12.0", "quoteVolume": "50000000"},
    ])

    chosen = select_volatile_symbols(db, client, max_symbols=1, min_volume_usdt=5_000_000)

    assert chosen == ["ETHUSDT"]
    doge = db.query(Symbol).filter(Symbol.symbol == "DOGEUSDT").one()
    assert doge.is_selected is False
    assert doge.is_auto_selected is False


def _signal(db, symbol, regime, age_minutes=1):
    row = Signal(
        symbol=symbol, timeframe="1h", strategy_name="none", regime=regime, action=SignalAction.NO_TRADE,
        created_at=datetime.now(timezone.utc) - timedelta(minutes=age_minutes),
    )
    db.add(row)
    db.flush()
    return row


def test_excludes_blow_off_moves_too_extreme_to_ever_trade(db):
    # A 45% pump is virtually guaranteed to classify as EXTREME_VOLATILITY
    # the moment the engine gets candles for it - picking it just wastes a
    # cycle. A smaller, still-tradeable mover should win instead.
    _symbol(db, "PUMPUSDT")
    _symbol(db, "ETHUSDT")

    client = FakeTickerClient([
        {"symbol": "PUMPUSDT", "priceChangePercent": "45.0", "quoteVolume": "50000000"},
        {"symbol": "ETHUSDT", "priceChangePercent": "8.5", "quoteVolume": "50000000"},
    ])

    chosen = select_volatile_symbols(db, client, max_symbols=1, min_volume_usdt=5_000_000)

    assert chosen == ["ETHUSDT"]


def test_rotates_away_from_a_symbol_already_stuck_in_extreme_volatility(db):
    # BEAMXUSDT is the biggest mover this round, but the engine's own most
    # recent regime reading for it (a few minutes ago) already says
    # EXTREME_VOLATILITY - every strategy refuses that regime, so
    # reselecting it would just repeat the same do-nothing cycle instead of
    # giving a tradeable symbol a chance.
    _symbol(db, "BEAMXUSDT")
    _symbol(db, "ETHUSDT")
    _signal(db, "BEAMXUSDT", "STRONG_UPTREND/EXTREME_VOLATILITY", age_minutes=5)

    client = FakeTickerClient([
        {"symbol": "BEAMXUSDT", "priceChangePercent": "15.0", "quoteVolume": "50000000"},
        {"symbol": "ETHUSDT", "priceChangePercent": "8.5", "quoteVolume": "50000000"},
    ])

    chosen = select_volatile_symbols(db, client, max_symbols=1, min_volume_usdt=5_000_000)

    assert chosen == ["ETHUSDT"]


def test_stale_extreme_regime_reading_does_not_block_reselection(db):
    _symbol(db, "BEAMXUSDT")
    _symbol(db, "ETHUSDT")
    _signal(db, "BEAMXUSDT", "STRONG_UPTREND/EXTREME_VOLATILITY", age_minutes=60)  # outside the lookback window

    client = FakeTickerClient([
        {"symbol": "BEAMXUSDT", "priceChangePercent": "15.0", "quoteVolume": "50000000"},
        {"symbol": "ETHUSDT", "priceChangePercent": "8.5", "quoteVolume": "50000000"},
    ])

    chosen = select_volatile_symbols(db, client, max_symbols=1, min_volume_usdt=5_000_000)

    assert chosen == ["BEAMXUSDT"]


def _position(db, symbol, status=PositionStatus.CLOSED, opened_minutes_ago=5, strategy_name="scalping"):
    row = Position(
        symbol=symbol, status=status, entry_price=1.0, quantity=1.0, mode=TradingMode.LIVE,
        strategy_name=strategy_name, opened_at=datetime.now(timezone.utc) - timedelta(minutes=opened_minutes_ago),
        closed_at=datetime.now(timezone.utc) if status == PositionStatus.CLOSED else None,
    )
    db.add(row)
    db.flush()
    return row


def test_rotates_away_from_a_recently_traded_symbol_even_if_still_top_mover(db):
    # TRUMPUSDT keeps winning the ranking every cycle (it's genuinely the
    # biggest mover), so without a cooldown the bot would trade the same
    # single pair indefinitely instead of "yendo variando" across symbols as
    # different things trend. A symbol just traded a few minutes ago should
    # sit out a round even though it's still on top.
    _symbol(db, "TRUMPUSDT", is_selected=True, is_auto=True)
    _symbol(db, "ETHUSDT")
    _position(db, "TRUMPUSDT", opened_minutes_ago=5)

    client = FakeTickerClient([
        {"symbol": "TRUMPUSDT", "priceChangePercent": "12.0", "quoteVolume": "50000000"},
        {"symbol": "ETHUSDT", "priceChangePercent": "8.5", "quoteVolume": "50000000"},
    ])

    chosen = select_volatile_symbols(db, client, max_symbols=1, min_volume_usdt=5_000_000)

    assert chosen == ["ETHUSDT"]


def test_cooldown_expires_after_the_configured_window(db):
    _symbol(db, "TRUMPUSDT")
    _symbol(db, "ETHUSDT")
    _position(db, "TRUMPUSDT", opened_minutes_ago=90)  # older than the 60-minute cooldown

    client = FakeTickerClient([
        {"symbol": "TRUMPUSDT", "priceChangePercent": "12.0", "quoteVolume": "50000000"},
        {"symbol": "ETHUSDT", "priceChangePercent": "8.5", "quoteVolume": "50000000"},
    ])

    chosen = select_volatile_symbols(db, client, max_symbols=1, min_volume_usdt=5_000_000)

    assert chosen == ["TRUMPUSDT"]


def test_never_deselects_a_symbol_with_a_currently_open_position(db):
    # The engine only ticks symbols with is_selected=True - deselecting one
    # mid-trade would silently stop checking its stop-loss/take-profit
    # forever. Even though TRUMPUSDT loses the ranking and is in cooldown,
    # its live position must keep it selected.
    _symbol(db, "TRUMPUSDT", is_selected=True, is_auto=True)
    _symbol(db, "ETHUSDT")
    _position(db, "TRUMPUSDT", status=PositionStatus.OPEN, opened_minutes_ago=5)

    client = FakeTickerClient([
        {"symbol": "TRUMPUSDT", "priceChangePercent": "1.0", "quoteVolume": "50000000"},
        {"symbol": "ETHUSDT", "priceChangePercent": "8.5", "quoteVolume": "50000000"},
    ])

    chosen = select_volatile_symbols(db, client, max_symbols=1, min_volume_usdt=5_000_000)

    assert chosen == ["ETHUSDT"]
    trump = db.query(Symbol).filter(Symbol.symbol == "TRUMPUSDT").one()
    assert trump.is_selected is True  # still monitored - has an open position
    assert trump.is_auto_selected is True
