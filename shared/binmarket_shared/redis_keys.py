"""Central place for every Redis key/channel name used across services.

Keeping these in one shared module prevents backend/trading-engine/market-data
from silently drifting apart on naming and makes the distributed-lock and
pub/sub contracts explicit and testable.
"""
from __future__ import annotations

# --- Distributed lock: prevents two trading-engine instances (or a stray
# duplicate process) from running the analysis/execution loop at the same
# time and double-placing orders. ---------------------------------------
ENGINE_LOCK_KEY = "binmarket:lock:trading-engine"
ENGINE_LOCK_TTL_SECONDS = 30

# --- Live market state (written by market-data, read by backend/engine) --
def ticker_key(symbol: str) -> str:
    return f"binmarket:ticker:{symbol.upper()}"


def orderbook_top_key(symbol: str) -> str:
    return f"binmarket:orderbook:top:{symbol.upper()}"


def latest_candle_key(symbol: str, timeframe: str) -> str:
    return f"binmarket:candle:latest:{symbol.upper()}:{timeframe}"


def ws_connection_status_key() -> str:
    return "binmarket:market-data:ws-status"


# --- Pub/sub channels ------------------------------------------------------
PRICE_UPDATES_CHANNEL = "binmarket:channel:price-updates"
SIGNAL_UPDATES_CHANNEL = "binmarket:channel:signal-updates"
BOT_STATE_CHANNEL = "binmarket:channel:bot-state"
ORDER_UPDATES_CHANNEL = "binmarket:channel:order-updates"

# --- Historical backfill job queue (list used as a simple FIFO queue) ----
BACKFILL_QUEUE_KEY = "binmarket:queue:backfill"

# --- Health heartbeats ------------------------------------------------------
def heartbeat_key(service: str) -> str:
    return f"binmarket:heartbeat:{service}"


HEARTBEAT_TTL_SECONDS = 30
