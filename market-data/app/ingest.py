"""Live market data ingestion (section 8 of the spec).

Subscribes to Binance's combined WebSocket stream for every currently
selected symbol (kline for every configured timeframe, rolling 24h ticker,
and top-of-book depth), writes closed candles to Postgres, and caches the
latest ticker/orderbook in Redis for the backend/trading-engine to read
without hitting Binance themselves. Restarts its own subscription whenever
the selected-symbol list changes, and always reconnects with backoff on
disconnect (via `BinanceWebSocketClient`) rather than silently going stale.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from binmarket_shared.binance.ws import BinanceWebSocketClient
from binmarket_shared.constants import TIMEFRAMES
from binmarket_shared.db.base import session_scope
from binmarket_shared.db.models import Candle, Symbol
from binmarket_shared.redis_keys import (
    orderbook_top_key,
    PRICE_UPDATES_CHANNEL,
    ticker_key,
    ws_connection_status_key,
)

logger = logging.getLogger("binmarket.market_data.ingest")

SYMBOL_POLL_INTERVAL_SECONDS = 20


def _selected_symbols() -> list[str]:
    with session_scope() as db:
        rows = db.execute(select(Symbol.symbol).where(Symbol.is_selected.is_(True))).scalars().all()
        return sorted(rows)


def _build_streams(symbols: list[str]) -> list[str]:
    streams: list[str] = []
    for symbol in symbols:
        s = symbol.lower()
        streams.append(f"{s}@ticker")
        streams.append(f"{s}@depth5@100ms")
        for tf in TIMEFRAMES:
            streams.append(f"{s}@kline_{tf}")
    return streams


def _upsert_candle(symbol: str, timeframe: str, k: dict) -> None:
    open_time = datetime.fromtimestamp(k["t"] / 1000, tz=timezone.utc)
    close_time = datetime.fromtimestamp(k["T"] / 1000, tz=timezone.utc)
    values = dict(
        symbol=symbol, timeframe=timeframe, open_time=open_time, close_time=close_time,
        open=float(k["o"]), high=float(k["h"]), low=float(k["l"]), close=float(k["c"]),
        volume=float(k["v"]), quote_volume=float(k["q"]), trades_count=int(k["n"]), is_closed=bool(k["x"]),
    )
    with session_scope() as db:
        stmt = pg_insert(Candle).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol", "timeframe", "open_time"],
            set_={k: v for k, v in values.items() if k not in ("symbol", "timeframe", "open_time")},
        )
        db.execute(stmt)


async def _handle_message(redis, message: dict) -> None:
    event_type = message.get("e")
    try:
        if event_type == "kline":
            k = message["k"]
            symbol = message["s"]
            timeframe = k["i"]
            await asyncio.to_thread(_upsert_candle, symbol, timeframe, k)
            if k["x"]:
                await redis.publish(PRICE_UPDATES_CHANNEL, json.dumps({"symbol": symbol, "price": float(k["c"]), "candle_closed": True, "timeframe": timeframe}))

        elif event_type == "24hrTicker":
            symbol = message["s"]
            payload = {
                "price": float(message["c"]),
                "price_change_pct_24h": float(message["P"]),
                "volume_24h": float(message["v"]),
                "high_24h": float(message["h"]),
                "low_24h": float(message["l"]),
            }
            await redis.set(ticker_key(symbol), json.dumps(payload))
            await redis.publish(PRICE_UPDATES_CHANNEL, json.dumps({"symbol": symbol, "price": payload["price"]}))

        elif "b" in message and "a" in message and "s" in message:
            # partial depth stream payload
            symbol = message["s"]
            bids, asks = message.get("b", []), message.get("a", [])
            if bids and asks:
                await redis.set(orderbook_top_key(symbol), json.dumps({"bid": float(bids[0][0]), "ask": float(asks[0][0])}))
    except Exception:
        logger.exception("Failed to handle market-data WS message: %s", event_type)


async def run_ingestion(redis, environment: str, stop_event: asyncio.Event) -> None:
    current_client: BinanceWebSocketClient | None = None
    current_task: asyncio.Task | None = None
    current_symbols: list[str] = []

    async def on_status_change(status: str) -> None:
        await redis.set(ws_connection_status_key(), status)
        if status == "disconnected":
            logger.warning("Market data WebSocket disconnected; signals will be paused until it reconnects")

    while not stop_event.is_set():
        symbols = _selected_symbols()
        if symbols != current_symbols:
            if current_client is not None:
                current_client.stop()
                if current_task is not None:
                    current_task.cancel()
            if symbols:
                streams = _build_streams(symbols)
                logger.info("Subscribing to %d streams for symbols: %s", len(streams), symbols)
                current_client = BinanceWebSocketClient(
                    streams, lambda msg: _handle_message(redis, msg), environment, on_status_change,
                )
                current_task = asyncio.create_task(current_client.run())
            else:
                current_client, current_task = None, None
                logger.info("No symbols selected yet; market-data is idle")
            current_symbols = symbols

        await asyncio.sleep(SYMBOL_POLL_INTERVAL_SECONDS)

    if current_client is not None:
        current_client.stop()
