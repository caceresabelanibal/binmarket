from __future__ import annotations

from binmarket_shared.db.models import TradingMode

from ._binance_common import BaseBinanceExecutionProvider


class BinanceTestnetExecutionProvider(BaseBinanceExecutionProvider):
    """Places real orders against Binance Spot Testnet. Requires a
    `BinanceClient` constructed with `environment="testnet"` — the caller
    (engine loop / manual trading endpoint) is responsible for that, so this
    class can never accidentally point at production."""

    mode = TradingMode.TESTNET
