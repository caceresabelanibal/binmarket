"""Reconnecting Binance combined-stream WebSocket client.

Used exclusively by the market-data service. Implements the reconnection
behaviour required by section 8 of the spec: on disconnect it reconnects with
exponential backoff, logs the incident, and — crucially — calls
`on_status_change("disconnected")` so downstream consumers know market data
may be stale and must not generate signals off it blindly.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Awaitable, Callable

import websockets
from websockets.exceptions import WebSocketException

from binmarket_shared.binance.client import Environment, ws_base_url

logger = logging.getLogger("binmarket.binance.ws")

OnMessage = Callable[[dict], Awaitable[None]]
OnStatusChange = Callable[[str], Awaitable[None]]


class BinanceWebSocketClient:
    def __init__(
        self,
        streams: list[str],
        on_message: OnMessage,
        environment: Environment = "testnet",
        on_status_change: OnStatusChange | None = None,
        max_backoff_seconds: float = 60.0,
    ):
        self._streams = streams
        self._on_message = on_message
        self._on_status_change = on_status_change
        self._base_url = ws_base_url(environment)
        self._max_backoff = max_backoff_seconds
        self._stop = asyncio.Event()

    def stop(self) -> None:
        self._stop.set()

    def _url(self) -> str:
        stream_path = "/".join(self._streams)
        return f"{self._base_url}/stream?streams={stream_path}"

    async def _emit_status(self, status: str) -> None:
        if self._on_status_change:
            await self._on_status_change(status)

    async def run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                async with websockets.connect(self._url(), ping_interval=20, ping_timeout=20) as ws:
                    logger.info("Connected to Binance WS: %s", self._streams)
                    await self._emit_status("connected")
                    backoff = 1.0
                    async for raw in ws:
                        if self._stop.is_set():
                            break
                        try:
                            payload = json.loads(raw)
                        except json.JSONDecodeError:
                            logger.warning("Malformed WS payload, skipping")
                            continue
                        data = payload.get("data", payload)
                        await self._on_message(data)
            except (WebSocketException, OSError) as exc:
                logger.warning("Binance WS disconnected (%s), reconnecting in %.1fs", exc, backoff)
                await self._emit_status("disconnected")
                if self._stop.is_set():
                    break
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self._max_backoff)
        await self._emit_status("stopped")
