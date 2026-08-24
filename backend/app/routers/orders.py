from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from binmarket_shared.db.models import Order, OrderSide, OrderStatus, OrderType, TradingMode, User

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

    class Config:
        from_attributes = True


@router.get("", response_model=list[OrderResponse])
def list_orders(
    symbol: str | None = None,
    mode: TradingMode | None = None,
    limit: int = Query(100, le=1000),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[Order]:
    query = db.query(Order)
    if symbol:
        query = query.filter(Order.symbol == symbol.upper())
    if mode:
        query = query.filter(Order.mode == mode)
    return query.order_by(Order.created_at.desc()).limit(limit).all()
