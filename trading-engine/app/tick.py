"""One full pass of the trading-engine loop: reload settings, rebuild the
right ExecutionProvider for the current mode, evaluate every selected
symbol, and (every ~10 minutes) record a portfolio snapshot. Written as
plain synchronous code — `main.py` runs it via `asyncio.to_thread` so it
never blocks the asyncio event loop, consistent with the sync-everywhere
decision documented in docs/architecture.md.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from binmarket_shared.binance.client import BinanceClient
from binmarket_shared.config import settings as env_settings
from binmarket_shared.db.base import session_scope
from binmarket_shared.db.models import AppSettings, PortfolioSnapshot, Symbol, TradingMode
from binmarket_shared.trading.engine_loop import process_symbol_tick
from binmarket_shared.trading.execution import get_execution_provider

from .snapshots import take_balance_snapshot, take_portfolio_snapshot

logger = logging.getLogger("binmarket.trading_engine.tick")

PRIMARY_TIMEFRAME = "1h"
SNAPSHOT_INTERVAL = timedelta(minutes=10)


def _binance_environment_for(mode: TradingMode) -> str:
    return "production" if mode == TradingMode.LIVE else "testnet"


def _current_price_fn(redis_client):
    import json

    from binmarket_shared.redis_keys import ticker_key

    def fn(symbol: str, fallback: float) -> float:
        raw = redis_client.get(ticker_key(symbol))
        return float(json.loads(raw)["price"]) if raw else fallback

    return fn


def run_tick(redis_client) -> None:
    with session_scope() as db:
        settings = db.get(AppSettings, 1)
        if settings is None:
            settings = AppSettings(id=1)
            db.add(settings)
            db.flush()

        binance_client = None
        if settings.mode == TradingMode.PAPER:
            provider = get_execution_provider("PAPER", db=db, redis_client=redis_client)
        else:
            binance_client = BinanceClient(
                env_settings.binance_api_key, env_settings.binance_api_secret, _binance_environment_for(settings.mode)
            )
            provider = get_execution_provider(settings.mode.value, binance_client=binance_client)

        try:
            symbols = [row.symbol for row in db.query(Symbol).filter(Symbol.is_selected.is_(True)).all()]
            for symbol in symbols:
                try:
                    process_symbol_tick(db, symbol, PRIMARY_TIMEFRAME, settings, provider, redis_client)
                except Exception:
                    logger.exception("Failed to process tick for %s", symbol)

            last_snapshot = (
                db.query(PortfolioSnapshot)
                .filter(PortfolioSnapshot.mode == settings.mode)
                .order_by(PortfolioSnapshot.taken_at.desc())
                .first()
            )
            if last_snapshot is None or datetime.now(timezone.utc) - last_snapshot.taken_at >= SNAPSHOT_INTERVAL:
                take_portfolio_snapshot(db, settings, provider, _current_price_fn(redis_client))
                take_balance_snapshot(db, settings, binance_client)
        finally:
            if binance_client is not None:
                binance_client.close()
