from __future__ import annotations

from binmarket_shared.db.models import TradingMode

from ._binance_common import BaseBinanceExecutionProvider


class BinanceLiveExecutionProvider(BaseBinanceExecutionProvider):
    """Places REAL orders with REAL money against Binance production.

    Deliberately has no extra "are you sure" logic of its own — that
    confirmation happens once, explicitly, when the user switches Settings
    into LIVE mode (section 4/42 of the spec). Once in LIVE mode, this class
    behaves identically to Testnet by design, because the whole point of
    Paper/Testnet is that they rehearse exactly this code path.
    """

    mode = TradingMode.LIVE
