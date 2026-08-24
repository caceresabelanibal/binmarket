from .base import ExecutionProvider, ExecutionResult
from .binance_live import BinanceLiveExecutionProvider
from .binance_testnet import BinanceTestnetExecutionProvider
from .paper import PaperExecutionProvider

__all__ = [
    "ExecutionProvider",
    "ExecutionResult",
    "PaperExecutionProvider",
    "BinanceTestnetExecutionProvider",
    "BinanceLiveExecutionProvider",
]


def get_execution_provider(mode: str, db=None, binance_client=None, redis_client=None):
    """Factory used by the engine loop / order manager so call sites never
    branch on `mode` themselves — they just ask for "the provider for this
    mode" (section 17 of the spec: same logic path, only the executor
    differs).
    """
    from binmarket_shared.db.models import TradingMode

    mode = TradingMode(mode) if not isinstance(mode, TradingMode) else mode
    if mode == TradingMode.PAPER:
        return PaperExecutionProvider(db, redis_client)
    if mode == TradingMode.TESTNET:
        return BinanceTestnetExecutionProvider(binance_client)
    if mode == TradingMode.LIVE:
        return BinanceLiveExecutionProvider(binance_client)
    raise ValueError(f"Unknown trading mode: {mode}")
