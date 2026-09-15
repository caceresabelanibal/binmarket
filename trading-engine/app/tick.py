"""One full pass of the trading-engine loop: reload settings, rebuild the
right ExecutionProvider for the current mode, evaluate every selected
symbol, and (every ~10 minutes) record a portfolio snapshot. Written as
plain synchronous code — `main.py` runs it via `asyncio.to_thread` so it
never blocks the asyncio event loop, consistent with the sync-everywhere
decision documented in docs/architecture.md.

Each unit of work below (reading settings, auto-selecting symbols, each
individual symbol's analysis/execution, the snapshot) opens and commits its
own `session_scope()`, deliberately never one shared session for the whole
tick. A single bad row (e.g. one symbol's regime label not fitting a column)
failing to flush poisons the *whole* SQLAlchemy session it happened in —
every later query on that session raises `PendingRollbackError` until an
explicit rollback, and it can even discard earlier, already-flushed work
from the *same* session when the outer transaction is torn down. With one
session per symbol, a failure analyzing symbol B can never roll back symbol
A's already-committed order/position update from the same tick — which
matters a great deal when A is a real, open LIVE position.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from binmarket_shared.binance.client import BinanceClient
from binmarket_shared.config import settings as env_settings
from binmarket_shared.db.base import session_scope
from binmarket_shared.db.models import (
    AppSettings,
    Candle,
    PortfolioSnapshot,
    Strategy,
    Symbol,
    SyncJob,
    SyncStatus,
    TradingMode,
)
from binmarket_shared.redis_keys import BACKFILL_QUEUE_KEY
from binmarket_shared.trading.engine_loop import REGIME_TIMEFRAME, process_symbol_tick
from binmarket_shared.trading.execution import get_execution_provider
from binmarket_shared.trading.symbol_selector import select_volatile_symbols

from .snapshots import take_balance_snapshot, take_portfolio_snapshot, take_real_account_snapshot

logger = logging.getLogger("binmarket.trading_engine.tick")

SNAPSHOT_INTERVAL = timedelta(minutes=10)

# Backtested against ~2 weeks of real candles across 20+ symbols before this
# order was set: trend_following was profitable on 16/20 symbols; scalping
# lost money in every take-profit/stop-loss combination tried (its ~0.5%
# target nets to ~0.2% after Binance's real fees+slippage, while its ~0.6%
# stop nets to ~0.9% loss - the fixed round-trip cost is too big a bite out
# of a target that small, for any entry-signal quality). Order here is a
# priority when more than one is eligible for the current regime, not a
# guess - see the analysis behind this change for the actual numbers.
# day_trading (requested directly by the user: weekly/daily context +
# end-of-day flatten) is tried first when enabled.
STRATEGY_PRIORITY_ORDER = ["day_trading", "trend_following", "mean_reversion", "breakout", "scalping"]


def _enabled_strategy_priority(db) -> list[str]:
    enabled = {row.name for row in db.query(Strategy).filter(Strategy.is_enabled.is_(True)).all()}
    return [name for name in STRATEGY_PRIORITY_ORDER if name in enabled]


AUTO_SELECT_GATE_KEY = "binmarket:trading-engine:auto-select-gate"
# Once a day (requested directly by the user: "todos los días toma esa
# decisión") - day_trading picks a fresh symbol pool each day and flattens
# everything by end of day, so there's no reason to re-pick more often than
# that; a 15-minute cadence was right for the old scalping pairing, not this.
AUTO_SELECT_INTERVAL_SECONDS = 24 * 60 * 60

# History for the Dashboard's "Capital real" card - independent of trading
# mode (PAPER/TESTNET/LIVE all still have a real account behind them), so
# gated on its own Redis cadence rather than tied to the per-mode
# PortfolioSnapshot check below.
REAL_ACCOUNT_SNAPSHOT_GATE_KEY = "binmarket:trading-engine:real-account-snapshot-gate"
REAL_ACCOUNT_SNAPSHOT_INTERVAL_SECONDS = 6 * 60 * 60

# A freshly auto-selected symbol has zero history. Regime classification
# needs 1h data - and every currently-enabled strategy trades on 1h too
# (trend_following/mean_reversion/breakout all use BaseStrategy's default
# preferred_timeframe), so this one backfill covers all of them. Scalping's
# own 5m backfill was dropped along with disabling it - see
# STRATEGY_PRIORITY_ORDER's comment for why.
_AUTO_SELECT_BACKFILL_SPECS = [
    (REGIME_TIMEFRAME, 14, 60),  # (timeframe, days back, min bars strategies/regime need)
]


def _binance_environment_for(mode: TradingMode) -> str:
    return "production" if mode == TradingMode.LIVE else "testnet"


def _current_price_fn(redis_client):
    from binmarket_shared.redis_keys import ticker_key

    def fn(symbol: str, fallback: float) -> float:
        raw = redis_client.get(ticker_key(symbol))
        return float(json.loads(raw)["price"]) if raw else fallback

    return fn


def _build_provider(mode: TradingMode, db, redis_client, binance_client):
    if mode == TradingMode.PAPER:
        return get_execution_provider("PAPER", db=db, redis_client=redis_client)
    return get_execution_provider(mode.value, binance_client=binance_client)


def _enqueue_backfill_if_needed(db, redis_client, symbol: str, timeframe: str, days_back: int, min_bars: int) -> None:
    existing = db.query(Candle).filter(Candle.symbol == symbol, Candle.timeframe == timeframe).count()
    if existing >= min_bars:
        return
    now = datetime.now(timezone.utc)
    job = SyncJob(
        symbol=symbol, timeframe=timeframe, status=SyncStatus.PENDING,
        range_start=now - timedelta(days=days_back), range_end=now,
    )
    db.add(job)
    # Must be committed — not just flushed — before the job reaches Redis:
    # market-data's worker picks it up on a separate DB connection/session,
    # and a plain flush() is only visible within *this* transaction. Without
    # the commit, the worker's `db.get(SyncJob, job_id)` can race ahead of
    # this transaction and find nothing, silently dropping the job (no error
    # logged anywhere) — exactly what happened the first time this ran live.
    db.commit()
    redis_client.rpush(BACKFILL_QUEUE_KEY, json.dumps({
        "job_id": job.id, "symbol": symbol, "timeframe": timeframe,
        "start": job.range_start.isoformat(), "end": job.range_end.isoformat(),
    }))
    logger.info("Queued backfill for freshly auto-selected %s (%s, %d days back)", symbol, timeframe, days_back)


def _run_auto_symbol_selection(redis_client) -> None:
    client = BinanceClient("", "", environment="production")  # public ticker endpoint, no key needed
    try:
        with session_scope() as db:
            settings = db.get(AppSettings, 1)
            chosen = select_volatile_symbols(db, client, settings.auto_select_max_symbols, settings.auto_select_min_volume_usdt)
            for symbol in chosen:
                for timeframe, days_back, min_bars in _AUTO_SELECT_BACKFILL_SPECS:
                    _enqueue_backfill_if_needed(db, redis_client, symbol, timeframe, days_back, min_bars)
    except Exception:
        logger.exception("Auto symbol selection failed")
    finally:
        client.close()


def _process_one_symbol(mode: TradingMode, symbol: str, redis_client, binance_client) -> None:
    with session_scope() as db:
        settings = db.get(AppSettings, 1)
        provider = _build_provider(mode, db, redis_client, binance_client)
        # Same priority for every symbol, manual or auto-selected - whichever
        # enabled strategy is actually eligible for (and, per the backtest,
        # actually profitable in) the current regime wins. Toggling a
        # strategy off in Settings/Strategies now really does take it out of
        # rotation (it didn't before - is_enabled was read from the DB but
        # never consulted here).
        priority = _enabled_strategy_priority(db)
        process_symbol_tick(db, symbol, settings, provider, redis_client, strategy_priority=priority)


def run_tick(redis_client) -> None:
    with session_scope() as db:
        settings = db.get(AppSettings, 1)
        if settings is None:
            settings = AppSettings(id=1)
            db.add(settings)
            db.flush()
        mode = settings.mode
        auto_select_enabled = settings.auto_select_symbols_enabled

    binance_client = None
    if mode != TradingMode.PAPER:
        binance_client = BinanceClient(
            env_settings.binance_api_key, env_settings.binance_api_secret, _binance_environment_for(mode)
        )

    try:
        if auto_select_enabled and redis_client.set(
            AUTO_SELECT_GATE_KEY, "1", nx=True, ex=AUTO_SELECT_INTERVAL_SECONDS
        ):
            _run_auto_symbol_selection(redis_client)

        if redis_client.set(
            REAL_ACCOUNT_SNAPSHOT_GATE_KEY, "1", nx=True, ex=REAL_ACCOUNT_SNAPSHOT_INTERVAL_SECONDS
        ):
            with session_scope() as db:
                take_real_account_snapshot(db)

        with session_scope() as db:
            selected = [row.symbol for row in db.query(Symbol).filter(Symbol.is_selected.is_(True)).all()]

        for symbol in selected:
            try:
                _process_one_symbol(mode, symbol, redis_client, binance_client)
            except Exception:
                logger.exception("Failed to process tick for %s", symbol)

        with session_scope() as db:
            settings = db.get(AppSettings, 1)
            last_snapshot = (
                db.query(PortfolioSnapshot)
                .filter(PortfolioSnapshot.mode == mode)
                .order_by(PortfolioSnapshot.taken_at.desc())
                .first()
            )
            if last_snapshot is None or datetime.now(timezone.utc) - last_snapshot.taken_at >= SNAPSHOT_INTERVAL:
                provider = _build_provider(mode, db, redis_client, binance_client)
                take_portfolio_snapshot(db, settings, provider, _current_price_fn(redis_client))
                take_balance_snapshot(db, settings, binance_client)
    finally:
        if binance_client is not None:
            binance_client.close()
