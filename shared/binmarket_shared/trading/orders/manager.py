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

from binmarket_shared.binance.filters import SymbolFilters
from binmarket_shared.db.models import (
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    PositionStatus,
    Signal,
    Symbol,
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


def _net_base_quantity(db: Session, symbol: str, result: ExecutionResult) -> float:
    """Binance often deducts the trading commission from the asset you just
    received (unless a BNB fee discount applies) — the account ends up
    holding strictly less than `filled_quantity`. Storing the gross amount
    on the position causes the SELL that closes it to fail later with
    "insufficient balance" (code -2010), a real bug this fixes: only the
    base asset's own commission actually reduces the base asset balance
    (a fee paid in the quote asset, e.g. USDT, doesn't touch it).
    """
    if not result.commission or not result.commission_asset:
        return result.filled_quantity
    row = db.query(Symbol).filter(Symbol.symbol == symbol).one_or_none()
    base_asset = row.base_asset if row else symbol[: -len("USDT")] if symbol.endswith("USDT") else None
    if base_asset and result.commission_asset == base_asset:
        return max(result.filled_quantity - result.commission, 0.0)
    return result.filled_quantity


def _commission_value_in_quote(
    amount: float | None, commission_asset: str | None, base_asset: str | None, fill_price: float,
) -> float:
    """`Order.commission_total` is stored in whatever asset Binance actually
    charged the fee in - usually the quote asset (USDT), but just as often
    the base asset (e.g. BTC, CHIP) when no BNB fee discount is active. PnL
    must stay in quote-asset terms throughout a trade; a real production bug
    subtracted a base-asset commission's raw amount as if it were already in
    USDT, wildly overstating that leg's cost (e.g. treating "0.131 CHIP" as
    "0.131 USDT" - about 25x too much on a ~$0.0388 coin) and could misfire
    the daily/weekly loss circuit breaker on a phantom loss.
    """
    if not amount:
        return 0.0
    if base_asset and commission_asset == base_asset:
        return amount * fill_price
    return amount


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
            entry_price = result.avg_fill_price
            stop_loss = signal.suggested_stop_loss
            take_profit = signal.suggested_take_profit

            # signal.suggested_stop_loss/take_profit were computed as fixed
            # price levels relative to signal.suggested_entry_price - the
            # best reference price available *before* the order filled. The
            # real fill can land far from that estimate (a stale ticker
            # fallback, real slippage, a fast-moving illiquid symbol), and a
            # stop-loss computed off the wrong reference can end up on the
            # wrong side of the *actual* entry entirely. Real incident: a
            # ~33% stale reference for a freshly-selected micro-cap put the
            # stop above the real entry price, closing the position 17
            # seconds after opening on the very first tick. Re-anchor both
            # levels to the real fill price, preserving the strategy's
            # intended relative risk/reward rather than trusting an absolute
            # price that may no longer be true.
            if signal.suggested_entry_price and signal.suggested_entry_price > 0:
                if stop_loss is not None:
                    stop_distance_pct = (signal.suggested_entry_price - stop_loss) / signal.suggested_entry_price
                    stop_loss = entry_price * (1 - stop_distance_pct)
                if take_profit is not None:
                    reward_distance_pct = (take_profit - signal.suggested_entry_price) / signal.suggested_entry_price
                    take_profit = entry_price * (1 + reward_distance_pct)

            position = Position(
                symbol=signal.symbol,
                entry_price=entry_price,
                quantity=_net_base_quantity(self.db, signal.symbol, result),
                stop_loss=stop_loss,
                take_profit=take_profit,
                highest_price_since_entry=entry_price,
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
                symbol=symbol, entry_price=result.avg_fill_price,
                quantity=_net_base_quantity(self.db, symbol, result),
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
        # The client_order_id is deterministic per *position* (not per attempt)
        # so a genuinely executed close is never repeated. But a REJECTED
        # order never touched the exchange at all - Binance refused it before
        # anything happened - so short-circuiting on it forever would mean a
        # single transient rejection (e.g. a momentary balance mismatch)
        # permanently disables closing the position, silently defeating its
        # own stop-loss/take-profit. Only skip re-placing the order when a
        # previous attempt actually reached the exchange.
        attempt = 1
        while True:
            suffix = () if attempt == 1 else (f"retry{attempt}",)
            client_order_id = _deterministic_client_order_id("CLOSE", position.id, mode.value, *suffix)
            existing = self._existing_order(client_order_id)
            if existing is None:
                break
            if existing.status != OrderStatus.REJECTED:
                return existing
            attempt += 1

        # position.quantity already nets out any commission paid in the base
        # asset (see _net_base_quantity), so it's an honest reflection of
        # what's actually held - but that exact amount is rarely a clean
        # multiple of the symbol's LOT_SIZE step, and Binance rejects a SELL
        # that isn't (-1013). Floor to the step size so the order is valid;
        # any leftover sub-step dust (a few cents at most) simply isn't
        # sellable on this pair and stays in the account.
        sell_quantity = position.quantity
        symbol_row = self.db.query(Symbol).filter(Symbol.symbol == position.symbol).one_or_none()
        if symbol_row and symbol_row.lot_step_size > 0:
            filters = SymbolFilters(
                symbol=position.symbol, tick_size=0.0, step_size=symbol_row.lot_step_size,
                min_qty=0.0, max_qty=0.0, min_notional=0.0,
            )
            floored = filters.round_quantity(position.quantity)
            if floored > 0:
                sell_quantity = floored

            # The real exchange balance can hold more than this position's
            # own tracked quantity - typically dust left over from a
            # *previous* position of the same symbol that itself couldn't
            # clear min_notional when it closed (see above). Only one
            # position per symbol is ever open at a time, so free balance
            # beyond what this position tracked is never "someone else's" -
            # sweeping it in here can be the difference between a position
            # that's stuck forever bleeding past its stop-loss and one that
            # actually closes. Real balances only exist outside PAPER mode
            # (PaperExecutionProvider's balance is a simulated USDT figure,
            # not a real per-asset balance, regardless of what asset is
            # asked for).
            if mode != TradingMode.PAPER and symbol_row.base_asset:
                actual_free = self.execution_provider.get_available_balance(symbol_row.base_asset)
                topped_up = filters.round_quantity(actual_free)
                if topped_up > sell_quantity:
                    sell_quantity = topped_up

        result = self.execution_provider.place_market_order(position.symbol, "SELL", sell_quantity)

        base_asset = symbol_row.base_asset if symbol_row else None
        opening_order = self.db.get(Order, position.opening_order_id) if position.opening_order_id else None
        opening_commission_quote = _commission_value_in_quote(
            opening_order.commission_total if opening_order else 0.0,
            opening_order.commission_asset if opening_order else None,
            base_asset, position.entry_price,
        )

        order = self._persist_order_and_trade(
            client_order_id, position.symbol, OrderSide.SELL, sell_quantity, result, mode,
            position.strategy_name, None, reason, is_manual,
        )

        if result.success and result.filled_quantity > 0:
            exit_price = result.avg_fill_price
            closing_commission_quote = _commission_value_in_quote(
                result.commission, result.commission_asset, base_asset, exit_price,
            )
            realized_pnl = (
                (exit_price - position.entry_price) * result.filled_quantity
                - opening_commission_quote
                - closing_commission_quote
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
