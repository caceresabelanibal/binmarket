"""Live market data ingestion (section 8 of the spec).

Subscribes to Binance's combined WebSocket stream for every currently
selected symbol, writes closed candles to Postgres, and caches the latest
ticker/orderbook in Redis for the backend/trading-engine to read without
hitting Binance themselves. Restarts its own subscription whenever the
selected-symbol list *or* the network-usage settings change, and always
reconnects with backoff on disconnect (via `BinanceWebSocketClient`) rather
than silently going stale.

Network usage is deliberately kept small by default: only the timeframes
the engine actually trades on are streamed (not all 8), and the order-book
depth stream runs at 1s instead of Binance's 100ms option — that alone is a
10x cut in the single highest-volume stream per symbol. Both are
user-configurable (Settings → Red) for anyone who wants full live multi-
timeframe charts badly enough to pay the extra bandwidth for it.
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
from binmarket_shared.db.models import AppSettings, Candle, Symbol
from binmarket_shared.redis_keys import (
    BANDWIDTH_BUCKET_TTL_SECONDS,
    bandwidth_bucket_key,
    orderbook_top_key,
    PRICE_UPDATES_CHANNEL,
    ticker_key,
    ws_connection_status_key,
)
from binmarket_shared.trading.engine_loop import REGIME_TIMEFRAME
from binmarket_shared.trading.strategies.scalping import ScalpingStrategy

logger = logging.getLogger("binmarket.market_data.ingest")

SYMBOL_POLL_INTERVAL_SECONDS = 20
ESSENTIAL_TIMEFRAMES = sorted({REGIME_TIMEFRAME, ScalpingStrategy.preferred_timeframe}, key=TIMEFRAMES.index)


def _selected_symbols_and_network_settings() -> tuple[list[str], bool, int]:
    with session_scope() as db:
        rows = db.execute(select(Symbol.symbol).where(Symbol.is_selected.is_(True))).scalars().all()
        settings = db.get(AppSettings, 1)
        all_timeframes = settings.stream_all_timeframes if settings else False
        depth_speed_ms = settings.orderbook_update_speed_ms if settings else 1000
        return sorted(rows), all_timeframes, depth_speed_ms


def _build_streams(symbols: list[str], all_timeframes: bool, depth_speed_ms: int) -> list[str]:
    timeframes = TIMEFRAMES if all_timeframes else ESSENTIAL_TIMEFRAMES
    depth_suffix = "@100ms" if depth_speed_ms == 100 else ""
    streams: list[str] = []
    for symbol in symbols:
        s = symbol.lower()
        streams.append(f"{s}@ticker")
        streams.append(f"{s}@depth5{depth_suffix}")
        for tf in timeframes:
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


def _is_depth_payload(message: dict) -> bool:
    # Binance's partial book depth stream payload is {"lastUpdateId": ..,
    # "bids": [...], "asks": [...]} - no "e"/"s" field at all, so this is
    # the only reliable way to recognize it.
    return "bids" in message and "asks" in message


async def _track_bandwidth(redis, event_type: str, message: dict, num_bytes: int) -> None:
    if event_type == "kline":
        category = "klines"
    elif event_type == "24hrTicker":
        category = "ticker"
    elif _is_depth_payload(message):
        category = "orderbook"
    else:
        return
    bucket = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
    key = bandwidth_bucket_key(category, bucket)
    await redis.incrby(key, num_bytes)
    await redis.expire(key, BANDWIDTH_BUCKET_TTL_SECONDS)


async def _handle_message(redis, message: dict, num_bytes: int, stream_name: str | None) -> None:
    event_type = message.get("e")
    try:
        await _track_bandwidth(redis, event_type, message, num_bytes)

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

        elif _is_depth_payload(message):
            # Partial depth payloads carry no symbol of their own - the
            # combined-stream name ("btcusdt@depth5") is the only place it's identifiable.
            if not stream_name:
                return
            symbol = stream_name.split("@")[0].upper()
            bids, asks = message.get("bids", []), message.get("asks", [])
            if bids and asks:
                await redis.set(orderbook_top_key(symbol), json.dumps({"bid": float(bids[0][0]), "ask": float(asks[0][0])}))
    except Exception:
        logger.exception("Failed to handle market-data WS message: %s", event_type)


async def run_ingestion(redis, environment: str, stop_event: asyncio.Event) -> None:
    current_client: BinanceWebSocketClient | None = None
    current_task: asyncio.Task | None = None
    current_key: tuple[tuple[str, ...], bool, int] | None = None

    async def on_status_change(status: str) -> None:
        await redis.set(ws_connection_status_key(), status)
        if status == "disconnected":
            logger.warning("Market data WebSocket disconnected; signals will be paused until it reconnects")

    while not stop_event.is_set():
        symbols, all_timeframes, depth_speed_ms = _selected_symbols_and_network_settings()
        key = (tuple(symbols), all_timeframes, depth_speed_ms)
        if key != current_key:
            if current_client is not None:
                current_client.stop()
                if current_task is not None:
                    current_task.cancel()
            if symbols:
                streams = _build_streams(symbols, all_timeframes, depth_speed_ms)
                logger.info(
                    "Subscribing to %d streams for symbols: %s (all_timeframes=%s, depth=%sms)",
                    len(streams), symbols, all_timeframes, depth_speed_ms,
                )
                current_client = BinanceWebSocketClient(
                    streams,
                    lambda msg, n, stream: _handle_message(redis, msg, n, stream),
                    environment,
                    on_status_change,
                )
                current_task = asyncio.create_task(current_client.run())
            else:
                current_client, current_task = None, None
                logger.info("No symbols selected yet; market-data is idle")
            current_key = key

        await asyncio.sleep(SYMBOL_POLL_INTERVAL_SECONDS)

    if current_client is not None:
        current_client.stop()
