from __future__ import annotations

from binmarket_shared.binance.client import BinanceClient
from binmarket_shared.config import settings
from binmarket_shared.db.models import TradingMode


def get_binance_client_for_mode(mode: TradingMode) -> BinanceClient:
    """TESTNET/LIVE always target the matching Binance backend; in PAPER mode
    (which never places real orders) we fall back to the BINANCE_ENVIRONMENT
    env var so the Settings/Binance screen can still validate configured
    keys before the user progresses the setup wizard."""
    if mode == TradingMode.LIVE:
        environment = "production"
    elif mode == TradingMode.TESTNET:
        environment = "testnet"
    else:
        environment = settings.binance_environment
    return BinanceClient(settings.binance_api_key, settings.binance_api_secret, environment)
