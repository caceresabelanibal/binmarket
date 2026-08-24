from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from binmarket_shared.db.models import AppSettings, OrderStatus, Position, PositionStatus, TradingMode
from binmarket_shared.quant.costs import apply_slippage
from binmarket_shared.redis_keys import ticker_key

from .base import ExecutionProvider, ExecutionResult


class PaperExecutionProvider(ExecutionProvider):
    """Simulates fills using real market prices with configured fee/slippage,
    exactly like Testnet/Live would, but never sends anything to Binance.

    Available balance is derived, not tracked as a separate mutable counter:
    `starting_balance + realized_pnl_all_time - value_tied_up_in_open_positions`.
    This keeps the paper ledger self-consistent with the `positions` table —
    there is no separate "paper wallet" that could drift out of sync.
    """

    mode = TradingMode.PAPER

    def __init__(self, db: Session, redis_client=None):
        self.db = db
        self.redis = redis_client

    def _settings(self) -> AppSettings:
        return self.db.get(AppSettings, 1)

    def get_available_balance(self, asset: str = "USDT") -> float:
        s = self._settings()
        starting = s.paper_starting_balance_usdt

        closed = self.db.execute(
            select(Position).where(Position.mode == TradingMode.PAPER, Position.status == PositionStatus.CLOSED)
        ).scalars().all()
        realized_pnl_total = sum(p.realized_pnl for p in closed)

        open_positions = self.db.execute(
            select(Position).where(Position.mode == TradingMode.PAPER, Position.status == PositionStatus.OPEN)
        ).scalars().all()
        tied_up = sum(p.entry_price * p.quantity for p in open_positions)

        return max(starting + realized_pnl_total - tied_up, 0.0)

    def get_symbol_price(self, symbol: str) -> float:
        if self.redis is not None:
            raw = self.redis.get(ticker_key(symbol))
            if raw:
                import json

                return float(json.loads(raw)["price"])
        raise RuntimeError(f"No cached price available for {symbol} to simulate a paper fill")

    def place_market_order(self, symbol: str, side: str, quantity: float) -> ExecutionResult:
        try:
            reference_price = self.get_symbol_price(symbol)
        except RuntimeError as exc:
            return ExecutionResult(False, OrderStatus.REJECTED, None, 0.0, None, 0.0, None, str(exc))

        s = self._settings()
        fill_price = apply_slippage(reference_price, side, s.default_slippage_pct)
        commission = fill_price * quantity * (s.taker_fee_pct / 100)

        return ExecutionResult(
            success=True,
            status=OrderStatus.FILLED,
            exchange_order_id=None,
            filled_quantity=quantity,
            avg_fill_price=fill_price,
            commission=commission,
            commission_asset="USDT",
        )

    def place_limit_order(self, symbol: str, side: str, quantity: float, price: float) -> ExecutionResult:
        """Simplified paper limit-order simulation: fills immediately if the
        limit price is already marketable, otherwise is rejected rather than
        left resting — resting-order matching is out of scope for the paper
        simulator (see docs/architecture.md, "explicitly simplified")."""
        reference_price = self.get_symbol_price(symbol)
        marketable = (side.upper() == "BUY" and price >= reference_price) or (
            side.upper() == "SELL" and price <= reference_price
        )
        if not marketable:
            return ExecutionResult(
                False, OrderStatus.REJECTED, None, 0.0, None, 0.0, None,
                "Paper trading no soporta órdenes límite en espera; el precio no es ejecutable de inmediato",
            )
        s = self._settings()
        commission = price * quantity * (s.taker_fee_pct / 100)
        return ExecutionResult(True, OrderStatus.FILLED, None, quantity, price, commission, "USDT")

    def cancel_order(self, symbol: str, exchange_order_id: str) -> bool:
        return True
