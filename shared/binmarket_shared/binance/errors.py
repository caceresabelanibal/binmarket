class BinanceAPIError(Exception):
    """Binance responded with an error payload (invalid key, filter violation, etc.)."""

    def __init__(self, status_code: int, code: int | None, message: str):
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(f"Binance API error {status_code} (code={code}): {message}")


class BinanceConnectivityError(Exception):
    """Network-level failure talking to Binance (timeout, DNS, connection reset)."""
