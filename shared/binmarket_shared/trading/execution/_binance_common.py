from __future__ import annotations

from binmarket_shared.binance.client import BinanceClient
from binmarket_shared.binance.errors import BinanceAPIError, BinanceConnectivityError
from binmarket_shared.db.models import OrderStatus

from .base import ExecutionProvider, ExecutionResult

_BINANCE_STATUS_MAP = {
    "NEW": OrderStatus.NEW,
    "PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED,
    "FILLED": OrderStatus.FILLED,
    "CANCELED": OrderStatus.CANCELED,
    "PENDING_CANCEL": OrderStatus.CANCELED,
    "REJECTED": OrderStatus.REJECTED,
    "EXPIRED": OrderStatus.EXPIRED,
}


class BaseBinanceExecutionProvider(ExecutionProvider):
    """Shared implementation for Testnet and Live: identical behaviour, the
    only difference is which `BinanceClient` (i.e. which base URL/keys) is
    injected — see `binance_testnet.py` / `binance_live.py`.
    """

    def __init__(self, client: BinanceClient):
        self.client = client

    def get_available_balance(self, asset: str = "USDT") -> float:
        account = self.client.get_account()
        for balance in account.get("balances", []):
            if balance["asset"] == asset:
                return float(balance["free"])
        return 0.0

    def get_symbol_price(self, symbol: str) -> float:
        ticker = self.client.get_ticker_24hr(symbol)
        return float(ticker["lastPrice"])

    def _from_order_response(self, response: dict) -> ExecutionResult:
        fills = response.get("fills", [])
        filled_qty = float(response.get("executedQty", 0.0))
        commission = sum(float(f.get("commission", 0.0)) for f in fills)
        commission_asset = fills[0]["commissionAsset"] if fills else None
        avg_price = None
        if filled_qty > 0 and fills:
            avg_price = sum(float(f["price"]) * float(f["qty"]) for f in fills) / filled_qty
        elif response.get("price"):
            avg_price = float(response["price"])

        status = _BINANCE_STATUS_MAP.get(response.get("status", ""), OrderStatus.NEW)
        return ExecutionResult(
            success=True,
            status=status,
            exchange_order_id=str(response.get("orderId")),
            filled_quantity=filled_qty,
            avg_fill_price=avg_price,
            commission=commission,
            commission_asset=commission_asset,
        )

    def place_market_order(self, symbol: str, side: str, quantity: float) -> ExecutionResult:
        try:
            response = self.client.create_order(symbol, side, "MARKET", quantity=quantity)
        except (BinanceAPIError, BinanceConnectivityError) as exc:
            return ExecutionResult(False, OrderStatus.REJECTED, None, 0.0, None, 0.0, None, str(exc))
        return self._from_order_response(response)

    def place_limit_order(self, symbol: str, side: str, quantity: float, price: float) -> ExecutionResult:
        try:
            response = self.client.create_order(
                symbol, side, "LIMIT", quantity=quantity, price=price, time_in_force="GTC"
            )
        except (BinanceAPIError, BinanceConnectivityError) as exc:
            return ExecutionResult(False, OrderStatus.REJECTED, None, 0.0, None, 0.0, None, str(exc))
        return self._from_order_response(response)

    def cancel_order(self, symbol: str, exchange_order_id: str) -> bool:
        try:
            self.client.cancel_order(symbol, order_id=int(exchange_order_id))
            return True
        except (BinanceAPIError, BinanceConnectivityError):
            return False
