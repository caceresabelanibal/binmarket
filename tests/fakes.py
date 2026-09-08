"""Lightweight test doubles — kept separate from conftest.py so individual
test modules can import just what they need.
"""
from __future__ import annotations

import json

from binmarket_shared.db.models import OrderStatus, TradingMode
from binmarket_shared.trading.execution.base import ExecutionProvider, ExecutionResult


class FakeExecutionProvider(ExecutionProvider):
    """Deterministic, in-memory stand-in for Paper/Testnet/Live — lets order
    manager / risk manager tests assert on behavior without needing Redis or
    a network call to Binance."""

    mode = TradingMode.PAPER

    def __init__(
        self,
        fill_price: float = 100.0,
        should_fail: bool = False,
        balance: float = 10_000.0,
        commission_asset: str = "USDT",
        base_asset_balance: float | None = None,
    ):
        self.fill_price = fill_price
        self.should_fail = should_fail
        self.balance = balance
        self.commission_asset = commission_asset
        # None means "not tracked separately" - callers that only care about
        # USDT capital never need to set this.
        self.base_asset_balance = base_asset_balance
        self.orders_placed: list[tuple[str, str, float]] = []

    def get_available_balance(self, asset: str = "USDT") -> float:
        if asset != "USDT":
            # Unless a test opts in, an unspecified base-asset balance is 0 -
            # not self.balance (that's a USDT capital figure and would be
            # nonsense misread as e.g. "10,000 BTC free").
            return self.base_asset_balance if self.base_asset_balance is not None else 0.0
        return self.balance

    def get_symbol_price(self, symbol: str) -> float:
        return self.fill_price

    def place_market_order(self, symbol: str, side: str, quantity: float) -> ExecutionResult:
        self.orders_placed.append((symbol, side, quantity))
        if self.should_fail:
            return ExecutionResult(False, OrderStatus.REJECTED, None, 0.0, None, 0.0, None, "simulated failure")
        if self.commission_asset == "USDT":
            commission = self.fill_price * quantity * 0.001
        else:
            commission = quantity * 0.001  # commission taken in the base asset itself
        return ExecutionResult(True, OrderStatus.FILLED, None, quantity, self.fill_price, commission, self.commission_asset)

    def place_limit_order(self, symbol: str, side: str, quantity: float, price: float) -> ExecutionResult:
        return self.place_market_order(symbol, side, quantity)

    def cancel_order(self, symbol: str, exchange_order_id: str) -> bool:
        return True


class FakeRedis:
    """In-memory stand-in for the subset of the redis-py API this codebase
    actually uses (get/set/publish/rpush/blpop)."""

    def __init__(self):
        self.store: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}
        self.published: list[tuple[str, str]] = []

    def get(self, key: str):
        return self.store.get(key)

    def set(self, key: str, value, ex: int | None = None, nx: bool = False):
        if nx and key in self.store:
            return False
        self.store[key] = value
        return True

    def delete(self, key: str):
        self.store.pop(key, None)

    def publish(self, channel: str, message: str):
        self.published.append((channel, message))

    def rpush(self, key: str, value: str):
        self.lists.setdefault(key, []).append(value)

    def llen(self, key: str) -> int:
        return len(self.lists.get(key, []))

    def lrange(self, key: str, start: int, end: int) -> list[str]:
        items = self.lists.get(key, [])
        stop = len(items) if end == -1 else end + 1
        return items[start:stop]

    def set_price(self, symbol: str, price: float):
        from binmarket_shared.redis_keys import ticker_key

        self.store[ticker_key(symbol)] = json.dumps({"price": price})


class AsyncFakeRedis:
    """Async-method counterpart to FakeRedis, for code paths that use
    redis.asyncio (market-data's ingestion pipeline)."""

    def __init__(self):
        self.store: dict[str, str] = {}
        self.counters: dict[str, int] = {}
        self.published: list[tuple[str, str]] = []

    async def get(self, key: str):
        return self.store.get(key)

    async def set(self, key: str, value, ex: int | None = None, nx: bool = False):
        if nx and key in self.store:
            return False
        self.store[key] = value
        return True

    async def publish(self, channel: str, message: str):
        self.published.append((channel, message))

    async def incrby(self, key: str, amount: int):
        self.counters[key] = self.counters.get(key, 0) + amount
        return self.counters[key]

    async def expire(self, key: str, seconds: int):
        return True
