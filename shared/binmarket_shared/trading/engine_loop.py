"""Per-symbol analysis-and-execution pipeline shared by the trading-engine's
continuous loop and (for a single on-demand check) the backend.

This module is the concrete wiring of the pipeline described in section 27
of the spec:

    Market Data -> Strategy -> AIAdvisor -> RiskManager -> Position Sizing
    -> OrderManager -> ExecutionProvider -> Binance/Paper -> DB -> Dashboard

Every step that could reject the trade (regime, cost gate, risk manager) does
so by recording *why* on the persisted `Signal` row, so the Decision Log can
always answer "why did/didn't it buy?" (section 25).
"""
from __future__ import annotations

import logging

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from binmarket_shared.binance.filters import SymbolFilters
from binmarket_shared.db.models import (
    AppSettings,
    Candle,
    Position,
    PositionStatus,
    RiskEvent,
    RiskSeverity,
    Signal,
    SignalAction,
    Symbol,
    TradingMode,
)
from binmarket_shared.quant.position_sizing import calculate_position_size
from binmarket_shared.quant.regime import classify_regime
from binmarket_shared.redis_keys import SIGNAL_UPDATES_CHANNEL, orderbook_top_key, ticker_key
from binmarket_shared.trading.ai.advisor import RuleBasedAdvisor
from binmarket_shared.trading.execution.base import ExecutionProvider
from binmarket_shared.trading.orders.manager import OrderManager
from binmarket_shared.trading.risk.manager import RiskManager
from binmarket_shared.trading.strategies.base import OpenPositionView, StrategyContext
from binmarket_shared.trading.strategies.registry import STRATEGY_REGISTRY, eligible_strategies, get_strategy

logger = logging.getLogger("binmarket.engine_loop")

DEFAULT_STRATEGY_PRIORITY = list(STRATEGY_REGISTRY.keys())
MAX_BARS_LOADED = 300

# Every strategy is judged against the same "is this a good environment to
# trade in" read, computed on this timeframe, regardless of which timeframe
# the winning strategy actually trades on (`strategy.preferred_timeframe`) —
# see BaseStrategy.preferred_timeframe for why.
REGIME_TIMEFRAME = "1h"


def load_candle_dataframe(db: Session, symbol: str, timeframe: str, limit: int = MAX_BARS_LOADED) -> pd.DataFrame:
    stmt = (
        select(Candle)
        .where(Candle.symbol == symbol, Candle.timeframe == timeframe, Candle.is_closed.is_(True))
        .order_by(Candle.open_time.desc())
        .limit(limit)
    )
    rows = list(db.execute(stmt).scalars().all())
    rows.reverse()
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    return pd.DataFrame(
        {
            "open": [r.open for r in rows],
            "high": [r.high for r in rows],
            "low": [r.low for r in rows],
            "close": [r.close for r in rows],
            "volume": [r.volume for r in rows],
        },
        index=pd.DatetimeIndex([r.open_time for r in rows], name="open_time"),
    )


def _read_ticker_price(redis_client, symbol: str, fallback: float) -> tuple[float, float | None, float | None, bool]:
    """Returns (price, best_bid, best_ask, is_live). `is_live` is False
    whenever `price` had to fall back to `fallback` (the last CLOSED
    candle's close, which for market-data's own bootstrap flow is often
    hours old) instead of a real cached WebSocket ticker tick - real
    incident: a freshly auto-selected, fast-moving micro-cap had no live
    ticker cached yet, so a stale hour-old close (33% away from the real
    market) got used as "current price" to size a brand new entry's
    stop-loss/take-profit, putting the stop on the wrong side of the real
    fill. Callers must never open a *new* position when this is False.
    """
    if redis_client is None:
        return fallback, None, None, False
    try:
        import json

        raw = redis_client.get(ticker_key(symbol))
        is_live = raw is not None
        price = float(json.loads(raw)["price"]) if raw else fallback
        book_raw = redis_client.get(orderbook_top_key(symbol))
        bid = ask = None
        if book_raw:
            book = json.loads(book_raw)
            bid, ask = float(book["bid"]), float(book["ask"])
        return price, bid, ask, is_live
    except Exception:
        logger.exception("Failed to read cached ticker for %s, using last candle close", symbol)
        return fallback, None, None, False


def _symbol_filters(db: Session, symbol: str) -> SymbolFilters | None:
    row = db.execute(select(Symbol).where(Symbol.symbol == symbol)).scalar_one_or_none()
    if row is None or row.lot_step_size <= 0:
        return None
    return SymbolFilters(symbol, row.price_tick_size, row.lot_step_size, row.min_qty, row.max_qty, row.min_notional)


def process_symbol_tick(
    db: Session,
    symbol: str,
    settings: AppSettings,
    execution_provider: ExecutionProvider,
    redis_client=None,
    strategy_priority: list[str] | None = None,
) -> Signal | None:
    regime_df = load_candle_dataframe(db, symbol, REGIME_TIMEFRAME)
    if len(regime_df) < 55:
        return None

    mode = settings.mode
    last_close = float(regime_df["close"].iloc[-1])
    current_price, best_bid, best_ask, price_is_live = _read_ticker_price(redis_client, symbol, last_close)
    regime = classify_regime(regime_df)

    risk_manager = RiskManager(db, settings)
    available_capital = execution_provider.get_available_balance("USDT")
    current_exposure = risk_manager.total_exposure_value(mode)
    symbol_filters = _symbol_filters(db, symbol)

    open_position = db.execute(
        select(Position).where(Position.symbol == symbol, Position.status == PositionStatus.OPEN, Position.mode == mode)
    ).scalar_one_or_none()

    order_manager = OrderManager(db, execution_provider, redis_client)

    if open_position is not None:
        return _handle_open_position(
            db, open_position, symbol, regime, current_price, settings, order_manager, mode, redis_client,
        )

    if not price_is_live:
        # No cached WebSocket ticker for this symbol yet (common right after
        # it's freshly selected, before market-data's subscription catches
        # up) - `current_price` fell back to the last CLOSED candle, which
        # can be hours old and wildly different from the real market for a
        # fast-moving symbol. Sizing a brand new entry - and its stop-loss/
        # take-profit - off that stale a reference is exactly what put a
        # stop-loss on the wrong side of the real fill for a real position.
        # An already-open position still gets monitored on the best price
        # available (never checking it at all would be worse); only new
        # entries are blocked here.
        signal = Signal(
            symbol=symbol, timeframe=REGIME_TIMEFRAME, strategy_name="none", regime=regime.label,
            action=SignalAction.NO_TRADE,
            reasons=["Sin precio en vivo confiable todavía para este símbolo (ticker recién seleccionado) — no se abren posiciones nuevas hasta tener datos en tiempo real"],
        )
        db.add(signal)
        db.flush()
        return signal

    strategies = eligible_strategies(regime, strategy_priority or DEFAULT_STRATEGY_PRIORITY)
    if not strategies:
        signal = Signal(
            symbol=symbol, timeframe=REGIME_TIMEFRAME, strategy_name="none", regime=regime.label,
            action=SignalAction.NO_TRADE, reasons=[f"Ninguna estrategia habilitada es elegible para el régimen {regime.label}"],
        )
        db.add(signal)
        db.flush()
        return signal

    strategy = strategies[0]
    entry_df = regime_df if strategy.preferred_timeframe == REGIME_TIMEFRAME else load_candle_dataframe(
        db, symbol, strategy.preferred_timeframe
    )
    if len(entry_df) < strategy.min_bars_required:
        signal = Signal(
            symbol=symbol, timeframe=strategy.preferred_timeframe, strategy_name=strategy.name, regime=regime.label,
            action=SignalAction.NO_TRADE,
            reasons=[
                f"Faltan datos históricos en {strategy.preferred_timeframe} para {symbol} "
                f"({len(entry_df)}/{strategy.min_bars_required} velas) — descargar histórico en Market"
            ],
        )
        db.add(signal)
        db.flush()
        return signal

    ctx = StrategyContext(
        df=entry_df, symbol=symbol, timeframe=strategy.preferred_timeframe, regime=regime, current_price=current_price,
        best_bid=best_bid, best_ask=best_ask, available_capital=available_capital,
        current_total_exposure_value=current_exposure, max_total_exposure_pct=settings.max_total_exposure_pct,
        max_position_size_pct=settings.max_position_size_pct, risk_per_trade_pct=settings.max_risk_per_trade_pct,
        taker_fee_pct=settings.taker_fee_pct, default_slippage_pct=settings.default_slippage_pct,
        min_expected_net_profit_pct=settings.min_expected_net_profit_pct, symbol_filters=symbol_filters,
        open_position=None,
    )
    strategy_signal = strategy.generate_signal(ctx)
    ai_recommendation = RuleBasedAdvisor().recommend(ctx, strategy_signal)

    signal = Signal(
        symbol=symbol, timeframe=strategy.preferred_timeframe, strategy_name=strategy.name, regime=regime.label,
        action=SignalAction(strategy_signal.action),
        opportunity_score=strategy_signal.scores.opportunity_score,
        trend_score=strategy_signal.scores.trend_score, momentum_score=strategy_signal.scores.momentum_score,
        volume_score=strategy_signal.scores.volume_score, volatility_score=strategy_signal.scores.volatility_score,
        risk_score=strategy_signal.scores.risk_score,
        reasons=strategy_signal.reasons + [f"IA (regla): confianza {ai_recommendation.confidence:.2f}"],
        expected_net_profit_pct=strategy_signal.expected_net_profit_pct,
        risk_reward_ratio=strategy_signal.risk_reward_ratio,
        suggested_entry_price=strategy_signal.entry_price,
        suggested_stop_loss=strategy_signal.stop_loss,
        suggested_take_profit=strategy_signal.take_profit,
    )
    db.add(signal)
    db.flush()

    if strategy_signal.action == "BUY" and strategy_signal.entry_price and strategy_signal.stop_loss:
        sizing = calculate_position_size(
            available_capital, settings.max_risk_per_trade_pct, strategy_signal.entry_price, strategy_signal.stop_loss,
            current_exposure, settings.max_total_exposure_pct, settings.max_position_size_pct, symbol_filters,
        )
        signal.suggested_quantity = sizing.quantity if sizing.is_tradeable else None

        if not sizing.is_tradeable:
            signal.reasons = signal.reasons + [f"Position sizing rechazó la operación: {sizing.rejection_reason}"]
        else:
            risk_check = risk_manager.check_automatic_entry(sizing.position_value, available_capital, mode)
            if not risk_check.allowed:
                signal.reasons = signal.reasons + [f"Risk Manager bloqueó la operación: {risk_check.reason}"]
                db.add(RiskEvent(
                    event_type="TRADE_BLOCKED", symbol=symbol, severity=RiskSeverity.WARNING,
                    details={"reason": risk_check.reason, "signal_id": signal.id},
                ))
            else:
                order_manager.open_position_from_signal(signal, sizing.quantity, mode)

    db.flush()
    if redis_client is not None:
        try:
            redis_client.publish(SIGNAL_UPDATES_CHANNEL, signal.id)
        except Exception:
            logger.exception("Failed to publish signal update to Redis")

    risk_manager.run_periodic_safety_checks(mode, available_capital)
    return signal


def _handle_open_position(
    db: Session,
    position: Position,
    symbol: str,
    regime,
    current_price: float,
    settings: AppSettings,
    order_manager: OrderManager,
    mode: TradingMode,
    redis_client,
) -> Signal:
    exit_reason = None

    if position.stop_loss and current_price <= position.stop_loss:
        exit_reason = f"Stop-loss alcanzado ({position.stop_loss:.4f})"
    elif position.take_profit and current_price >= position.take_profit:
        exit_reason = f"Take-profit alcanzado ({position.take_profit:.4f})"
    elif position.trailing_stop_pct:
        highest = max(position.highest_price_since_entry or position.entry_price, current_price)
        position.highest_price_since_entry = highest
        trailing_level = highest * (1 - position.trailing_stop_pct / 100)
        if current_price <= trailing_level:
            exit_reason = f"Trailing stop alcanzado ({trailing_level:.4f})"

    strategy = get_strategy(position.strategy_name) if position.strategy_name in STRATEGY_REGISTRY else None
    monitoring_timeframe = strategy.preferred_timeframe if strategy else REGIME_TIMEFRAME

    if exit_reason is None and strategy is not None:
        df = load_candle_dataframe(db, symbol, strategy.preferred_timeframe)
        if len(df) >= strategy.min_bars_required:
            ctx = StrategyContext(
                df=df, symbol=symbol, timeframe=strategy.preferred_timeframe, regime=regime, current_price=current_price,
                best_bid=current_price, best_ask=current_price, available_capital=0.0,
                current_total_exposure_value=0.0, max_total_exposure_pct=settings.max_total_exposure_pct,
                max_position_size_pct=settings.max_position_size_pct, risk_per_trade_pct=settings.max_risk_per_trade_pct,
                taker_fee_pct=settings.taker_fee_pct, default_slippage_pct=settings.default_slippage_pct,
                min_expected_net_profit_pct=settings.min_expected_net_profit_pct,
                open_position=OpenPositionView(
                    entry_price=position.entry_price, quantity=position.quantity, stop_loss=position.stop_loss,
                    take_profit=position.take_profit, trailing_stop_pct=position.trailing_stop_pct,
                    highest_price_since_entry=position.highest_price_since_entry, opened_at=position.opened_at,
                ),
            )
            should_exit, reason = strategy.should_exit_on_deterioration(ctx)
            if should_exit:
                exit_reason = reason

    action = SignalAction.SELL if exit_reason else SignalAction.HOLD
    signal = Signal(
        symbol=symbol, timeframe=monitoring_timeframe, strategy_name=position.strategy_name or "unknown", regime=regime.label,
        action=action,
        reasons=[exit_reason] if exit_reason else ["Posición abierta en seguimiento; sin condición de salida todavía"],
    )
    db.add(signal)
    db.flush()

    if exit_reason:
        order_manager.close_position(position, exit_reason, mode)

    if redis_client is not None:
        try:
            redis_client.publish(SIGNAL_UPDATES_CHANNEL, signal.id)
        except Exception:
            logger.exception("Failed to publish signal update to Redis")

    return signal
