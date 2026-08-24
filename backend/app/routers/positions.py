from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.redis_client import redis_client
from binmarket_shared.db.models import Position, PositionStatus, TradingMode, User
from binmarket_shared.redis_keys import ticker_key

router = APIRouter(prefix="/api/positions", tags=["positions"])


class PositionResponse(BaseModel):
    id: str
    symbol: str
    status: PositionStatus
    entry_price: float
    quantity: float
    stop_loss: float | None
    take_profit: float | None
    realized_pnl: float
    unrealized_pnl_pct: float | None = None
    exit_price: float | None
    close_reason: str | None
    mode: TradingMode
    strategy_name: str | None
    opened_at: datetime
    closed_at: datetime | None

    class Config:
        from_attributes = True


@router.get("", response_model=list[PositionResponse])
def list_positions(
    status_filter: PositionStatus | None = None,
    mode: TradingMode | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[PositionResponse]:
    query = db.query(Position)
    if status_filter:
        query = query.filter(Position.status == status_filter)
    if mode:
        query = query.filter(Position.mode == mode)
    rows = query.order_by(Position.opened_at.desc()).limit(200).all()

    results = []
    for row in rows:
        response = PositionResponse.model_validate(row)
        if row.status == PositionStatus.OPEN:
            raw = redis_client.get(ticker_key(row.symbol))
            if raw:
                current_price = json.loads(raw)["price"]
                response.unrealized_pnl_pct = (current_price - row.entry_price) / row.entry_price * 100
        results.append(response)
    return results
