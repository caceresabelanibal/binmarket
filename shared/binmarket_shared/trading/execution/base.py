"""ExecutionProvider interface (section 17 of the spec).

Exactly one interface, three implementations (Paper / Testnet / Live). The
Order Manager and engine loop are written entirely against this interface —
switching modes never changes any other code path, which is what lets Paper
Trading be a genuine rehearsal of Live rather than a separate simulation.

Stop-loss / take-profit / trailing-stop are *not* placed as native exchange
conditional orders here: they are monitored by the engine loop against the
stored position and closed with a plain market order through this same
interface. This keeps exit behaviour identical across all three modes
without needing OCO-order support in Paper mode. See docs/architecture.md.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from binmarket_shared.db.models import OrderStatus, TradingMode


@dataclass
class ExecutionResult:
    success: bool
    status: OrderStatus
    exchange_order_id: str | None
    filled_quantity: float
    avg_fill_price: float | None
    commission: float
    commission_asset: str | None
    error: str | None = None


class ExecutionProvider(ABC):
    mode: TradingMode

    @abstractmethod
    def get_available_balance(self, asset: str = "USDT") -> float:
        ...

    @abstractmethod
    def get_symbol_price(self, symbol: str) -> float:
        ...

    @abstractmethod
    def place_market_order(self, symbol: str, side: str, quantity: float) -> ExecutionResult:
        ...

    @abstractmethod
    def place_limit_order(self, symbol: str, side: str, quantity: float, price: float) -> ExecutionResult:
        ...

    @abstractmethod
    def cancel_order(self, symbol: str, exchange_order_id: str) -> bool:
        ...
