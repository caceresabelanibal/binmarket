"""Order Manager (section 18 of the spec).

The only place in the codebase that turns a decision into a persisted Order
+ Trade + Position. Idempotency is enforced at the database level: the
client_order_id is *deterministic* (derived from the signal/position id), so
if the engine loop is ever invoked twice for the same signal (a retry after a
crash, a duplicate wake-up), the unique constraint on `orders.client_order_id`
rejects the second insert and this class simply returns the order that
already exists instead of placing a second real order.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from binmarket_shared.db.models import (
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    PositionStatus,
    Signal,
    Trade,
    TradingMode,
)
from binmarket_shared.notifications import AlertEvent, AlertLevel, notify
from binmarket_shared.redis_keys import ORDER_UPDATES_CHANNEL

from ..execution.base import ExecutionProvider, ExecutionResult

logger = logging.getLogger("binmarket.orders")


def _deterministic_client_order_id(*parts: str) -> str:
    digest = hashlib.sha1(":".join(parts).encode()).hexdigest()
    return f"bm{digest[:30]}"


class OrderManager:
    def __init__(self, db: Session, execution_provider: ExecutionProvider, redis_client=None):
        self.db = db
        self.execution_provider = execution_provider
        self.redis = redis_client

    def _existing_order(self, client_order_id: str) -> Order | None:
        return self.db.query(Order).filter(Order.client_order_id == client_order_id).one_or_none()

    def _persist_order_and_trade(
        self,
        client_order_id: str,
        symbol: str,
        side: OrderSide,
        quantity: float,
        result: ExecutionResult,
        mode: TradingMode,
        strategy_name: str | None,
        signal_id: str | None,
        reason: str,
        is_manual: bool,
    ) -> Order:
        if not result.success and result.error:
            # The execution provider's error (e.g. Binance's actual rejection
            # reason) is otherwise lost — it must survive onto the persisted
            # order, or nobody can ever tell *why* a real order failed.
            reason = f"{reason} | ERROR DE EJECUCIÓN: {result.error}" if reason else f"ERROR DE EJECUCIÓN: {result.error}"
            logger.warning("Order execution failed for %s %s %s: %s", side, quantity, symbol, result.error)

        order = Order(
            client_order_id=client_order_id,
            exchange_order_id=result.exchange_order_id,
            symbol=symbol,
            side=side,
            type=OrderType.MARKET,
            status=result.status,
            quantity=quantity,
            filled_quantity=result.filled_quantity,
            avg_fill_price=result.avg_fill_price,
            commission_total=result.commission,
            commission_asset=result.commission_asset,
            mode=mode,
            strategy_name=strategy_name,
            signal_id=signal_id,
            reason=reason,
            is_manual=is_manual,
        )
        try:
            self.db.add(order)
            self.db.flush()
        except IntegrityError:
            self.db.rollback()
            existing = self._existing_order(client_order_id)
            if existing:
                logger.warning("Duplicate order suppressed by idempotency key: %s", client_order_id)
                return existing
            raise

        if result.filled_quantity > 0 and result.avg_fill_price:
            self.db.add(Trade(
                order_id=order.id,
                symbol=symbol,
                side=side,
                price=result.avg_fill_price,
                quantity=result.filled_quantity,
                quote_quantity=result.filled_quantity * result.avg_fill_price,
                commission=result.commission,
                commission_asset=result.commission_asset,
            ))
        if not result.success:
            order.closed_at = datetime.now(timezone.utc)

        if self.redis is not None:
            try:
                self.redis.publish(ORDER_UPDATES_CHANNEL, order.id)
            except Exception:
                logger.exception("Failed to publish order update to Redis")

        return order

    def open_position_from_signal(
        self,
        signal: Signal,
        quantity: float,
        mode: TradingMode,
        is_manual: bool = False,
    ) -> tuple[Order, Position | None]:
        client_order_id = _deterministic_client_order_id("OPEN", str(signal.id), signal.symbol, mode.value)

        existing = self._existing_order(client_order_id)
        if existing is not None:
            existing_position = (
                self.db.query(Position).filter(Position.opening_order_id == existing.id).one_or_none()
            )
            return existing, existing_position

        result = self.execution_provider.place_market_order(signal.symbol, "BUY", quantity)
        order = self._persist_order_and_trade(
            client_order_id, signal.symbol, OrderSide.BUY, quantity, result, mode,
            signal.strategy_name, signal.id, "; ".join(signal.reasons[:5]), is_manual,
        )

        signal.acted_upon = True
        signal.order_id = order.id

        position = None
        if result.success and result.filled_quantity > 0:
            position = Position(
                symbol=signal.symbol,
                entry_price=result.avg_fill_price,
                quantity=result.filled_quantity,
                stop_loss=signal.suggested_stop_loss,
                take_profit=signal.suggested_take_profit,
                highest_price_since_entry=result.avg_fill_price,
                mode=mode,
                strategy_name=signal.strategy_name,
                opening_order_id=order.id,
            )
            self.db.add(position)
            self.db.flush()

            notify(AlertEvent(
                title=f"BUY {signal.symbol}",
                message=f"Compra ejecutada: {result.filled_quantity} {signal.symbol} @ {result.avg_fill_price:.4f} ({mode.value})",
                level=AlertLevel.INFO,
                category="buy",
                metadata={"symbol": signal.symbol, "quantity": result.filled_quantity, "price": result.avg_fill_price},
            ))
        else:
            notify(AlertEvent(
                title=f"Error al comprar {signal.symbol}",
                message=result.error or "La orden no pudo ejecutarse",
                level=AlertLevel.WARNING,
                category="error",
            ))

        return order, position

    def open_manual_position(
        self,
        symbol: str,
        quantity: float,
        stop_loss: float | None,
        take_profit: float | None,
        mode: TradingMode,
        idempotency_key: str,
    ) -> tuple[Order, Position | None]:
        """Manual BUY (section 23): not tied to a strategy Signal, but goes
        through the exact same OrderManager/ExecutionProvider path as an
        automatic trade — the only difference is `is_manual=True` and
        `strategy_name=None`. The caller (manual-trading endpoint) is
        responsible for having already passed the Risk Manager's
        `check_manual_entry` before calling this.
        """
        client_order_id = _deterministic_client_order_id("MANUAL_OPEN", symbol, mode.value, idempotency_key)

        existing = self._existing_order(client_order_id)
        if existing is not None:
            existing_position = (
                self.db.query(Position).filter(Position.opening_order_id == existing.id).one_or_none()
            )
            return existing, existing_position

        result = self.execution_provider.place_market_order(symbol, "BUY", quantity)
        order = self._persist_order_and_trade(
            client_order_id, symbol, OrderSide.BUY, quantity, result, mode,
            None, None, "Orden manual", True,
        )

        position = None
        if result.success and result.filled_quantity > 0:
            position = Position(
                symbol=symbol, entry_price=result.avg_fill_price, quantity=result.filled_quantity,
                stop_loss=stop_loss, take_profit=take_profit, highest_price_since_entry=result.avg_fill_price,
                mode=mode, strategy_name=None, opening_order_id=order.id,
            )
            self.db.add(position)
            self.db.flush()
            notify(AlertEvent(
                title=f"BUY manual {symbol}",
                message=f"Compra manual ejecutada: {result.filled_quantity} {symbol} @ {result.avg_fill_price:.4f} ({mode.value})",
                level=AlertLevel.INFO, category="buy",
            ))
        else:
            notify(AlertEvent(
                title=f"Error en compra manual {symbol}", message=result.error or "La orden no pudo ejecutarse",
                level=AlertLevel.WARNING, category="error",
            ))

        return order, position

    def close_position(
        self,
        position: Position,
        reason: str,
        mode: TradingMode,
        is_manual: bool = False,
    ) -> Order:
        client_order_id = _deterministic_client_order_id("CLOSE", position.id, mode.value)

        existing = self._existing_order(client_order_id)
        if existing is not None:
            return existing

        result = self.execution_provider.place_market_order(position.symbol, "SELL", position.quantity)

        opening_order = self.db.get(Order, position.opening_order_id) if position.opening_order_id else None
        opening_commission = opening_order.commission_total if opening_order else 0.0

        order = self._persist_order_and_trade(
            client_order_id, position.symbol, OrderSide.SELL, position.quantity, result, mode,
            position.strategy_name, None, reason, is_manual,
        )

        if result.success and result.filled_quantity > 0:
            exit_price = result.avg_fill_price
            realized_pnl = (
                (exit_price - position.entry_price) * result.filled_quantity
                - opening_commission
                - result.commission
            )
            position.status = PositionStatus.CLOSED
            position.exit_price = exit_price
            position.realized_pnl = realized_pnl
            position.close_reason = reason
            position.closing_order_id = order.id
            position.closed_at = datetime.now(timezone.utc)

            notify(AlertEvent(
                title=f"SELL {position.symbol}",
                message=(
                    f"Venta ejecutada: {result.filled_quantity} {position.symbol} @ {exit_price:.4f} "
                    f"({mode.value}). PnL: {realized_pnl:+.2f} USDT. Motivo: {reason}"
                ),
                level=AlertLevel.INFO if realized_pnl >= 0 else AlertLevel.WARNING,
                category="sell",
                metadata={"symbol": position.symbol, "pnl": realized_pnl, "reason": reason},
            ))
        else:
            notify(AlertEvent(
                title=f"Error al vender {position.symbol}",
                message=result.error or "La orden de cierre no pudo ejecutarse",
                level=AlertLevel.CRITICAL,
                category="error",
            ))

        return order
