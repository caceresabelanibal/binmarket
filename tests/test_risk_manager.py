"""Section 37 of the spec, made concrete: these are the tests that guarantee
capital preservation regardless of what a strategy or signal wants to do.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from binmarket_shared.db.models import Position, PositionStatus, TradingMode
from binmarket_shared.trading.risk.manager import RiskManager


def _closed_position(db, mode, realized_pnl, closed_at=None):
    p = Position(
        symbol="BTCUSDT", entry_price=100, quantity=1, status=PositionStatus.CLOSED,
        realized_pnl=realized_pnl, mode=mode, closed_at=closed_at or datetime.now(timezone.utc),
    )
    db.add(p)
    db.flush()
    return p


def _open_position(db, mode, entry_price=100, quantity=1):
    p = Position(symbol="BTCUSDT", entry_price=entry_price, quantity=quantity, status=PositionStatus.OPEN, mode=mode)
    db.add(p)
    db.flush()
    return p


def test_bot_off_blocks_automatic_entry(db, app_settings):
    app_settings.bot_enabled = False
    rm = RiskManager(db, app_settings)
    result = rm.check_automatic_entry(position_value=100, available_capital=10_000, mode=TradingMode.PAPER)
    assert result.allowed is False
    assert "apagado" in result.reason


def test_bot_on_allows_entry_within_limits(db, app_settings):
    app_settings.bot_enabled = True
    rm = RiskManager(db, app_settings)
    result = rm.check_automatic_entry(position_value=100, available_capital=10_000, mode=TradingMode.PAPER)
    assert result.allowed is True


def test_emergency_stop_blocks_automatic_entry_even_if_bot_enabled(db, app_settings):
    app_settings.bot_enabled = True
    app_settings.emergency_stop_active = True
    app_settings.emergency_stop_reason = "test trip"
    rm = RiskManager(db, app_settings)
    result = rm.check_automatic_entry(position_value=100, available_capital=10_000, mode=TradingMode.PAPER)
    assert result.allowed is False


def test_emergency_stop_blocks_manual_entry_too(db, app_settings):
    """Manual trades bypass the bot ON/OFF switch, but must NEVER bypass
    Emergency Stop — that's the one thing nothing should override."""
    app_settings.emergency_stop_active = True
    rm = RiskManager(db, app_settings)
    result = rm.check_manual_entry(position_value=100, available_capital=10_000, mode=TradingMode.PAPER)
    assert result.allowed is False


def test_max_open_positions_enforced(db, app_settings):
    app_settings.bot_enabled = True
    app_settings.max_open_positions = 2
    _open_position(db, TradingMode.PAPER)
    _open_position(db, TradingMode.PAPER)
    rm = RiskManager(db, app_settings)
    result = rm.check_automatic_entry(position_value=50, available_capital=10_000, mode=TradingMode.PAPER)
    assert result.allowed is False
    assert "posiciones abiertas" in result.reason


def test_max_total_exposure_enforced(db, app_settings):
    app_settings.bot_enabled = True
    app_settings.max_total_exposure_pct = 20
    _open_position(db, TradingMode.PAPER, entry_price=1000, quantity=1)  # $1,000 exposure already
    rm = RiskManager(db, app_settings)
    # Capital $10,000, 20% cap = $2,000 total; a new $1,500 position would push it to $2,500
    result = rm.check_automatic_entry(position_value=1_500, available_capital=10_000, mode=TradingMode.PAPER)
    assert result.allowed is False
    assert "exposición" in result.reason


def test_max_position_size_pct_enforced(db, app_settings):
    app_settings.bot_enabled = True
    app_settings.max_position_size_pct = 5
    rm = RiskManager(db, app_settings)
    result = rm.check_automatic_entry(position_value=600, available_capital=10_000, mode=TradingMode.PAPER)
    assert result.allowed is False


def test_daily_loss_limit_triggers_emergency_stop_and_disables_bot(db, app_settings):
    app_settings.bot_enabled = True
    app_settings.max_daily_loss_pct = 5
    _closed_position(db, TradingMode.PAPER, realized_pnl=-600)  # -6% of $10,000
    rm = RiskManager(db, app_settings)
    rm.run_periodic_safety_checks(TradingMode.PAPER, available_capital=10_000)
    assert app_settings.emergency_stop_active is True
    assert app_settings.bot_enabled is False


def test_daily_loss_within_limit_does_not_trigger_emergency_stop(db, app_settings):
    app_settings.bot_enabled = True
    app_settings.max_daily_loss_pct = 5
    _closed_position(db, TradingMode.PAPER, realized_pnl=-200)  # -2% of $10,000
    rm = RiskManager(db, app_settings)
    rm.run_periodic_safety_checks(TradingMode.PAPER, available_capital=10_000)
    assert app_settings.emergency_stop_active is False


def test_consecutive_losses_triggers_emergency_stop(db, app_settings):
    app_settings.bot_enabled = True
    app_settings.max_consecutive_losses = 3
    for _ in range(3):
        _closed_position(db, TradingMode.PAPER, realized_pnl=-10)
    rm = RiskManager(db, app_settings)
    rm.run_periodic_safety_checks(TradingMode.PAPER, available_capital=10_000)
    assert app_settings.emergency_stop_active is True


def test_a_single_win_breaks_the_losing_streak(db, app_settings):
    app_settings.bot_enabled = True
    app_settings.max_consecutive_losses = 3
    _closed_position(db, TradingMode.PAPER, realized_pnl=-10, closed_at=datetime.now(timezone.utc) - timedelta(minutes=30))
    _closed_position(db, TradingMode.PAPER, realized_pnl=+50, closed_at=datetime.now(timezone.utc) - timedelta(minutes=20))
    _closed_position(db, TradingMode.PAPER, realized_pnl=-10, closed_at=datetime.now(timezone.utc) - timedelta(minutes=10))
    rm = RiskManager(db, app_settings)
    assert rm.consecutive_losing_trades(TradingMode.PAPER) == 1


def test_clearing_emergency_stop_resets_the_losing_streak(db, app_settings):
    """Regression test for a real production bug: a human clears Emergency
    Stop after a real losing streak and turns the bot back on, but the very
    next periodic safety check re-reads the same already-acknowledged
    losses and re-trips instantly - the manual "encender" button could
    never actually stick. Clearing the stop must reset what counts as "the
    streak" to that moment, the same way a real circuit breaker's reset
    switch starts fresh instead of re-tripping on the fault that's already
    been dealt with.
    """
    app_settings.bot_enabled = True
    app_settings.max_consecutive_losses = 3
    for _ in range(3):
        _closed_position(db, TradingMode.PAPER, realized_pnl=-10)
    rm = RiskManager(db, app_settings)
    assert rm.consecutive_losing_trades(TradingMode.PAPER) == 3

    rm.clear_emergency_stop("admin")
    assert rm.consecutive_losing_trades(TradingMode.PAPER) == 0

    rm.run_periodic_safety_checks(TradingMode.PAPER, available_capital=10_000)
    assert app_settings.emergency_stop_active is False  # did NOT instantly re-trip on old history


def test_new_losses_after_a_reset_still_trip_the_breaker(db, app_settings):
    # The reset only wipes the *old* streak - it's not a permanent bypass.
    app_settings.bot_enabled = True
    app_settings.max_consecutive_losses = 2
    rm = RiskManager(db, app_settings)
    rm.clear_emergency_stop("admin")

    for _ in range(2):
        _closed_position(db, TradingMode.PAPER, realized_pnl=-10)
    rm.run_periodic_safety_checks(TradingMode.PAPER, available_capital=10_000)
    assert app_settings.emergency_stop_active is True


def test_emergency_stop_cannot_be_re_enabled_by_toggling_bot_alone(db, app_settings):
    """Guards against a subtle bug: turning bot_enabled back on must not by
    itself let automatic trading resume while Emergency Stop is active."""
    app_settings.emergency_stop_active = True
    app_settings.bot_enabled = True  # someone flips this without clearing the stop
    rm = RiskManager(db, app_settings)
    result = rm.check_automatic_entry(position_value=10, available_capital=10_000, mode=TradingMode.PAPER)
    assert result.allowed is False
