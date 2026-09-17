"""backend/app/routers/binance.py's _trade_window_stats - the aggregation
behind the Dashboard's "operaciones ganadoras/perdedoras" cards (requested
directly by the user). Imported via the backend service, same pattern
_service_import.py already provides for trading-engine/market-data.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from binmarket_shared.db.models import Position, PositionStatus, TradingMode

from ._service_import import import_service_module

_trade_window_stats = import_service_module("backend", "routers.binance")._trade_window_stats


def _closed_position(db, mode, realized_pnl, closed_at, symbol="BTCUSDT"):
    p = Position(
        symbol=symbol, entry_price=100.0, quantity=1.0, mode=mode,
        status=PositionStatus.CLOSED, realized_pnl=realized_pnl, closed_at=closed_at,
    )
    db.add(p)
    db.flush()
    return p


def test_counts_and_sums_wins_and_losses_within_the_window(db):
    now = datetime.now(timezone.utc)
    _closed_position(db, TradingMode.LIVE, 5.0, now - timedelta(hours=1))
    _closed_position(db, TradingMode.LIVE, 3.0, now - timedelta(hours=2))
    _closed_position(db, TradingMode.LIVE, -2.0, now - timedelta(hours=3))

    stats = _trade_window_stats(db, TradingMode.LIVE, now - timedelta(hours=24), now)

    assert stats.winning_trades == 2
    assert stats.losing_trades == 1
    assert stats.winning_amount_usdt == 8.0
    assert stats.losing_amount_usdt == -2.0
    assert stats.net_pnl_usdt == 6.0


def test_a_trade_with_exactly_zero_pnl_counts_as_a_loss_not_a_win(db):
    now = datetime.now(timezone.utc)
    _closed_position(db, TradingMode.LIVE, 0.0, now - timedelta(hours=1))

    stats = _trade_window_stats(db, TradingMode.LIVE, now - timedelta(hours=24), now)

    assert stats.winning_trades == 0
    assert stats.losing_trades == 1


def test_trades_outside_the_window_are_excluded(db):
    now = datetime.now(timezone.utc)
    _closed_position(db, TradingMode.LIVE, 5.0, now - timedelta(days=10))

    stats = _trade_window_stats(db, TradingMode.LIVE, now - timedelta(hours=24), now)

    assert stats.winning_trades == 0
    assert stats.net_pnl_usdt == 0.0


def test_open_positions_are_never_counted(db):
    now = datetime.now(timezone.utc)
    open_position = Position(
        symbol="ETHUSDT", entry_price=100.0, quantity=1.0, mode=TradingMode.LIVE,
        status=PositionStatus.OPEN, realized_pnl=0.0,
    )
    db.add(open_position)
    db.flush()

    stats = _trade_window_stats(db, TradingMode.LIVE, now - timedelta(hours=24), now)

    assert stats.winning_trades == 0
    assert stats.losing_trades == 0


def test_paper_trades_do_not_leak_into_live_stats(db):
    now = datetime.now(timezone.utc)
    _closed_position(db, TradingMode.PAPER, 100.0, now - timedelta(hours=1))
    _closed_position(db, TradingMode.LIVE, 5.0, now - timedelta(hours=1))

    stats = _trade_window_stats(db, TradingMode.LIVE, now - timedelta(hours=24), now)

    assert stats.winning_trades == 1
    assert stats.winning_amount_usdt == 5.0
