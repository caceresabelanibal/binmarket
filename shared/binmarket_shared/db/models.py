"""All SQLAlchemy ORM models for BinMarket.

Every service (backend, trading-engine, market-data) imports these models
from `binmarket_shared` instead of redefining them, so there is exactly one
schema definition and one set of Alembic migrations (in /database).
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from binmarket_shared.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class TradingMode(str, enum.Enum):
    PAPER = "PAPER"
    TESTNET = "TESTNET"
    LIVE = "LIVE"


class SignalAction(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    NO_TRADE = "NO_TRADE"


class OrderSide(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, enum.Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
    TRAILING_STOP = "TRAILING_STOP"


class OrderStatus(str, enum.Enum):
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class PositionStatus(str, enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class BotEventAction(str, enum.Enum):
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"
    EMERGENCY_STOP = "EMERGENCY_STOP"
    MODE_CHANGED = "MODE_CHANGED"


class RiskSeverity(str, enum.Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class BacktestStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"


class SyncStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AppSettings(Base):
    """Singleton row (id=1) holding the entire operational configuration."""

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)

    mode: Mapped[TradingMode] = mapped_column(Enum(TradingMode, name="trading_mode"), default=TradingMode.PAPER)

    bot_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    bot_enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    bot_disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    bot_changed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bot_change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    max_risk_per_trade_pct: Mapped[float] = mapped_column(Float, default=1.0)
    max_total_exposure_pct: Mapped[float] = mapped_column(Float, default=50.0)
    max_position_size_pct: Mapped[float] = mapped_column(Float, default=20.0)
    max_daily_loss_pct: Mapped[float] = mapped_column(Float, default=5.0)
    max_weekly_loss_pct: Mapped[float] = mapped_column(Float, default=10.0)
    max_open_positions: Mapped[int] = mapped_column(Integer, default=5)
    max_consecutive_losses: Mapped[int] = mapped_column(Integer, default=4)

    min_expected_net_profit_pct: Mapped[float] = mapped_column(Float, default=0.15)
    taker_fee_pct: Mapped[float] = mapped_column(Float, default=0.10)
    maker_fee_pct: Mapped[float] = mapped_column(Float, default=0.10)
    default_slippage_pct: Mapped[float] = mapped_column(Float, default=0.05)

    paper_starting_balance_usdt: Mapped[float] = mapped_column(Float, default=10_000.0)

    emergency_stop_active: Mapped[bool] = mapped_column(Boolean, default=False)
    emergency_stop_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Set to "now" whenever a human clears Emergency Stop - the moment they
    # explicitly acknowledge a losing streak and choose to resume. Positions
    # closed *before* this timestamp no longer count toward
    # consecutive_losing_trades(): without this, clearing the stop and
    # turning the bot back on could never actually stick, because the very
    # next periodic safety check re-reads the same already-acknowledged
    # streak and re-trips immediately, before a single new trade could ever
    # happen to break it. NULL means "never cleared" - every closed position
    # counts, the original behavior.
    losing_streak_reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    wizard_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    wizard_step: Mapped[int] = mapped_column(Integer, default=1)

    auto_select_symbols_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_select_max_symbols: Mapped[int] = mapped_column(Integer, default=1)
    auto_select_min_volume_usdt: Mapped[float] = mapped_column(Float, default=5_000_000.0)

    # Network usage controls (market-data's Binance WebSocket subscriptions).
    # Off by default: only stream the 1h (regime) + 5m (scalping) timeframes
    # instead of all 8, and the order-book depth stream at 1s instead of
    # 100ms — the single biggest bandwidth cut, since 100ms means 10
    # messages/sec per symbol just for the top of book.
    stream_all_timeframes: Mapped[bool] = mapped_column(Boolean, default=False)
    orderbook_update_speed_ms: Mapped[int] = mapped_column(Integer, default=1000)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Symbol(Base, TimestampMixin):
    __tablename__ = "symbols"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    base_asset: Mapped[str] = mapped_column(String(16))
    quote_asset: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="TRADING")

    is_selected: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    is_auto_selected: Mapped[bool] = mapped_column(Boolean, default=False)

    price_tick_size: Mapped[float] = mapped_column(Float, default=0.0)
    lot_step_size: Mapped[float] = mapped_column(Float, default=0.0)
    min_qty: Mapped[float] = mapped_column(Float, default=0.0)
    max_qty: Mapped[float] = mapped_column(Float, default=0.0)
    min_notional: Mapped[float] = mapped_column(Float, default=0.0)


class Candle(Base):
    __tablename__ = "candles"
    __table_args__ = (UniqueConstraint("symbol", "timeframe", "open_time", name="uq_candle_symbol_tf_time"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    timeframe: Mapped[str] = mapped_column(String(8), index=True)
    open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    close_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)
    quote_volume: Mapped[float] = mapped_column(Float, default=0.0)
    trades_count: Mapped[int] = mapped_column(Integer, default=0)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=True)


class Strategy(Base, TimestampMixin):
    __tablename__ = "strategies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    version: Mapped[str] = mapped_column(String(16), default="1.0.0")
    description: Mapped[str] = mapped_column(Text, default="")
    parameters: Mapped[dict] = mapped_column(JSONB, default=dict)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    timeframe: Mapped[str] = mapped_column(String(8))
    strategy_name: Mapped[str] = mapped_column(String(64))
    # "STRONG_DOWNTREND/EXTREME_VOLATILITY" (RegimeReading.label's longest
    # possible value) is 36 chars — 64 leaves real headroom, not just enough
    # to fit today's exact strings.
    regime: Mapped[str] = mapped_column(String(64), default="UNKNOWN")

    action: Mapped[SignalAction] = mapped_column(Enum(SignalAction, name="signal_action"))

    opportunity_score: Mapped[float] = mapped_column(Float, default=0.0)
    trend_score: Mapped[float] = mapped_column(Float, default=0.0)
    momentum_score: Mapped[float] = mapped_column(Float, default=0.0)
    volume_score: Mapped[float] = mapped_column(Float, default=0.0)
    volatility_score: Mapped[float] = mapped_column(Float, default=0.0)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)

    reasons: Mapped[list] = mapped_column(JSONB, default=list)

    expected_net_profit_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_reward_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)

    suggested_entry_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    suggested_quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    suggested_stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    suggested_take_profit: Mapped[float | None] = mapped_column(Float, nullable=True)

    acted_upon: Mapped[bool] = mapped_column(Boolean, default=False)
    order_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("orders.id"), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class Order(Base, TimestampMixin):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    client_order_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    exchange_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    symbol: Mapped[str] = mapped_column(String(32), index=True)
    side: Mapped[OrderSide] = mapped_column(Enum(OrderSide, name="order_side"))
    type: Mapped[OrderType] = mapped_column(Enum(OrderType, name="order_type"))
    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus, name="order_status"), default=OrderStatus.NEW)

    quantity: Mapped[float] = mapped_column(Float)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_price: Mapped[float | None] = mapped_column(Float, nullable=True)

    filled_quantity: Mapped[float] = mapped_column(Float, default=0.0)
    avg_fill_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    commission_total: Mapped[float] = mapped_column(Float, default=0.0)
    commission_asset: Mapped[str | None] = mapped_column(String(16), nullable=True)

    mode: Mapped[TradingMode] = mapped_column(Enum(TradingMode, name="order_mode"))
    strategy_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    signal_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    is_manual: Mapped[bool] = mapped_column(Boolean, default=False)

    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    trades: Mapped[list["Trade"]] = relationship(back_populates="order")


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    order_id: Mapped[str] = mapped_column(String(36), ForeignKey("orders.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    side: Mapped[OrderSide] = mapped_column(Enum(OrderSide, name="trade_side"))
    price: Mapped[float] = mapped_column(Float)
    quantity: Mapped[float] = mapped_column(Float)
    quote_quantity: Mapped[float] = mapped_column(Float)
    commission: Mapped[float] = mapped_column(Float, default=0.0)
    commission_asset: Mapped[str | None] = mapped_column(String(16), nullable=True)
    exchange_trade_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    order: Mapped["Order"] = relationship(back_populates="trades")


class Position(Base, TimestampMixin):
    __tablename__ = "positions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[PositionStatus] = mapped_column(
        Enum(PositionStatus, name="position_status"), default=PositionStatus.OPEN, index=True
    )

    entry_price: Mapped[float] = mapped_column(Float)
    quantity: Mapped[float] = mapped_column(Float)

    stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    trailing_stop_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    highest_price_since_entry: Mapped[float | None] = mapped_column(Float, nullable=True)

    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    close_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    mode: Mapped[TradingMode] = mapped_column(Enum(TradingMode, name="position_mode"))
    strategy_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    opening_order_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    closing_order_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StrategyRun(Base):
    __tablename__ = "strategy_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    strategy_name: Mapped[str] = mapped_column(String(64), index=True)
    symbol: Mapped[str] = mapped_column(String(32))
    mode: Mapped[TradingMode] = mapped_column(Enum(TradingMode, name="strategy_run_mode"))
    status: Mapped[str] = mapped_column(String(16), default="RUNNING")
    metrics: Mapped[dict] = mapped_column(JSONB, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Backtest(Base):
    __tablename__ = "backtests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(128))
    symbol: Mapped[str] = mapped_column(String(32))
    timeframe: Mapped[str] = mapped_column(String(8))
    strategy_name: Mapped[str] = mapped_column(String(64))
    parameters: Mapped[dict] = mapped_column(JSONB, default=dict)

    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    train_end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    validation_end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    initial_capital: Mapped[float] = mapped_column(Float, default=10_000.0)
    fee_pct: Mapped[float] = mapped_column(Float, default=0.1)
    slippage_pct: Mapped[float] = mapped_column(Float, default=0.05)

    is_walk_forward: Mapped[bool] = mapped_column(Boolean, default=False)

    status: Mapped[BacktestStatus] = mapped_column(
        Enum(BacktestStatus, name="backtest_status"), default=BacktestStatus.PENDING
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    results: Mapped[dict] = mapped_column(JSONB, default=dict)
    equity_curve: Mapped[list] = mapped_column(JSONB, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    trades: Mapped[list["BacktestTrade"]] = relationship(back_populates="backtest")


class BacktestTrade(Base):
    __tablename__ = "backtest_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    backtest_id: Mapped[str] = mapped_column(String(36), ForeignKey("backtests.id"), index=True)
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    exit_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    side: Mapped[str] = mapped_column(String(8), default="LONG")
    entry_price: Mapped[float] = mapped_column(Float)
    exit_price: Mapped[float] = mapped_column(Float)
    quantity: Mapped[float] = mapped_column(Float)
    pnl: Mapped[float] = mapped_column(Float)
    pnl_pct: Mapped[float] = mapped_column(Float)
    fees_paid: Mapped[float] = mapped_column(Float, default=0.0)
    exit_reason: Mapped[str] = mapped_column(String(64), default="")

    backtest: Mapped["Backtest"] = relationship(back_populates="trades")


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    mode: Mapped[TradingMode] = mapped_column(Enum(TradingMode, name="portfolio_mode"))
    total_equity: Mapped[float] = mapped_column(Float)
    cash_balance: Mapped[float] = mapped_column(Float)
    invested_value: Mapped[float] = mapped_column(Float)
    pnl_today: Mapped[float] = mapped_column(Float, default=0.0)
    pnl_week: Mapped[float] = mapped_column(Float, default=0.0)
    pnl_month: Mapped[float] = mapped_column(Float, default=0.0)
    pnl_total: Mapped[float] = mapped_column(Float, default=0.0)
    roi_pct: Mapped[float] = mapped_column(Float, default=0.0)
    drawdown_pct: Mapped[float] = mapped_column(Float, default=0.0)


class BalanceSnapshot(Base):
    __tablename__ = "balance_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    mode: Mapped[TradingMode] = mapped_column(Enum(TradingMode, name="balance_mode"))
    asset: Mapped[str] = mapped_column(String(16))
    free: Mapped[float] = mapped_column(Float)
    locked: Mapped[float] = mapped_column(Float)
    usd_value: Mapped[float] = mapped_column(Float, default=0.0)


class RealAccountSnapshot(Base):
    """History for the Dashboard's "Capital real" card - the user's actual
    Binance spot wallet value, independent of trading mode. Taken every 6h
    by the trading-engine and pruned to the last 30 days (see
    trading-engine/app/snapshots.py::take_real_account_snapshot)."""

    __tablename__ = "real_account_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    total_usdt: Mapped[float] = mapped_column(Float)
    total_ars: Mapped[float | None] = mapped_column(Float, nullable=True)
    usdt_ars_rate: Mapped[float | None] = mapped_column(Float, nullable=True)


class BotEvent(Base):
    __tablename__ = "bot_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    action: Mapped[BotEventAction] = mapped_column(Enum(BotEventAction, name="bot_event_action"))
    performed_by: Mapped[str] = mapped_column(String(64), default="system")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    context: Mapped[dict] = mapped_column(JSONB, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class RiskEvent(Base):
    __tablename__ = "risk_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    symbol: Mapped[str | None] = mapped_column(String(32), nullable=True)
    severity: Mapped[RiskSeverity] = mapped_column(Enum(RiskSeverity, name="risk_severity"), default=RiskSeverity.WARNING)
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class SystemLog(Base):
    __tablename__ = "system_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    level: Mapped[str] = mapped_column(String(16), default="INFO")
    service: Mapped[str] = mapped_column(String(32), index=True)
    message: Mapped[str] = mapped_column(Text)
    context: Mapped[dict] = mapped_column(JSONB, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class SyncJob(Base, TimestampMixin):
    __tablename__ = "sync_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    timeframe: Mapped[str] = mapped_column(String(8))
    status: Mapped[SyncStatus] = mapped_column(Enum(SyncStatus, name="sync_status"), default=SyncStatus.PENDING)
    range_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    range_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_synced_open_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    candles_synced: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
