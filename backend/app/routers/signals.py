from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from binmarket_shared.db.models import Signal, SignalAction, User

router = APIRouter(prefix="/api/signals", tags=["signals"])


class SignalResponse(BaseModel):
    id: str
    symbol: str
    timeframe: str
    strategy_name: str
    regime: str
    action: SignalAction
    opportunity_score: float
    trend_score: float
    momentum_score: float
    volume_score: float
    volatility_score: float
    risk_score: float
    reasons: list[str]
    expected_net_profit_pct: float | None
    risk_reward_ratio: float | None
    suggested_entry_price: float | None
    suggested_quantity: float | None
    suggested_stop_loss: float | None
    suggested_take_profit: float | None
    acted_upon: bool
    order_id: str | None
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("", response_model=list[SignalResponse])
def list_signals(
    symbol: str | None = None,
    action: SignalAction | None = None,
    limit: int = Query(100, le=1000),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[Signal]:
    query = db.query(Signal)
    if symbol:
        query = query.filter(Signal.symbol == symbol.upper())
    if action:
        query = query.filter(Signal.action == action)
    return query.order_by(Signal.created_at.desc()).limit(limit).all()


@router.get("/{signal_id}", response_model=SignalResponse)
def get_signal(signal_id: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> Signal:
    return db.get(Signal, signal_id)
