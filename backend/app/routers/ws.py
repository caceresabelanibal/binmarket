"""Frontend WebSocket fan-out (section 8/21 of the spec).

The frontend opens exactly one WebSocket to the backend; the backend
subscribes to the Redis pub/sub channels that market-data/trading-engine
publish to and forwards every message as-is. This keeps the browser
decoupled from Redis entirely and lets any number of browser tabs share the
same underlying subscription infrastructure.
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.security import COOKIE_NAME, decode_access_token
from app.redis_client import get_async_redis
from binmarket_shared.redis_keys import BOT_STATE_CHANNEL, ORDER_UPDATES_CHANNEL, PRICE_UPDATES_CHANNEL, SIGNAL_UPDATES_CHANNEL

logger = logging.getLogger("binmarket.ws")
router = APIRouter(tags=["ws"])

CHANNELS = [PRICE_UPDATES_CHANNEL, SIGNAL_UPDATES_CHANNEL, BOT_STATE_CHANNEL, ORDER_UPDATES_CHANNEL]


@router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    token = websocket.cookies.get(COOKIE_NAME)
    if not token or not decode_access_token(token):
        await websocket.close(code=4401)
        return

    await websocket.accept()
    redis = get_async_redis()
    pubsub = redis.pubsub()
    await pubsub.subscribe(*CHANNELS)

    async def forward_messages() -> None:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            await websocket.send_text(json.dumps({"channel": message["channel"], "data": message["data"]}))

    forward_task = asyncio.create_task(forward_messages())
    try:
        while True:
            # We don't expect meaningful client -> server messages, but keep
            # reading so a disconnect is detected promptly.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        forward_task.cancel()
        await pubsub.unsubscribe(*CHANNELS)
        await pubsub.close()
        await redis.close()
