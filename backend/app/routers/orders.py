from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from binmarket_shared.db.models import Order, OrderSide, OrderStatus, OrderType, Position, PositionStatus, TradingMode, User

router = APIRouter(prefix="/api/orders", tags=["orders"])


class OrderResponse(BaseModel):
    id: str
    client_order_id: str
    exchange_order_id: str | None
    symbol: str
    side: OrderSide
    type: OrderType
    status: OrderStatus
    quantity: float
    filled_quantity: float
    avg_fill_price: float | None
    commission_total: float
    mode: TradingMode
    strategy_name: str | None
    reason: str
    is_manual: bool
    created_at: datetime

    # The buy and sell that open/close the same position, paired up so the
    # UI can show "compró a X, vendió a Y, GANÓ/PERDIÓ" instead of two
    # unrelated-looking rows. Both legs of a pair carry the same position_id
    # and the same (final) result once the position is closed.
    position_id: str | None = None
    position_status: PositionStatus | None = None
    position_realized_pnl: float | None = None

    class Config:
        from_attributes = True


@router.get("", response_model=list[OrderResponse])
def list_orders(
    symbol: str | None = None,
    mode: TradingMode | None = None,
    limit: int = Query(100, le=1000),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[OrderResponse]:
    query = db.query(Order)
    if symbol:
        query = query.filter(Order.symbol == symbol.upper())
    if mode:
        query = query.filter(Order.mode == mode)
    orders = query.order_by(Order.created_at.desc()).limit(limit).all()

    order_ids = [o.id for o in orders]
    position_by_order_id: dict[str, Position] = {}
    if order_ids:
        positions = db.query(Position).filter(
            or_(Position.opening_order_id.in_(order_ids), Position.closing_order_id.in_(order_ids))
        ).all()
        for p in positions:
            if p.opening_order_id:
                position_by_order_id[p.opening_order_id] = p
            if p.closing_order_id:
                position_by_order_id[p.closing_order_id] = p

    result = []
    for o in orders:
        p = position_by_order_id.get(o.id)
        result.append(OrderResponse(
            id=o.id, client_order_id=o.client_order_id, exchange_order_id=o.exchange_order_id,
            symbol=o.symbol, side=o.side, type=o.type, status=o.status, quantity=o.quantity,
            filled_quantity=o.filled_quantity, avg_fill_price=o.avg_fill_price,
            commission_total=o.commission_total, mode=o.mode, strategy_name=o.strategy_name,
            reason=o.reason, is_manual=o.is_manual, created_at=o.created_at,
            position_id=p.id if p else None,
            position_status=p.status if p else None,
            position_realized_pnl=p.realized_pnl if (p and p.status == PositionStatus.CLOSED) else None,
        ))
    return result
