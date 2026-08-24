from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from binmarket_shared.db.models import BotEvent, BotEventAction, Signal, SignalAction, SystemLog, User

router = APIRouter(prefix="/api/logs", tags=["logs"])


class DecisionLogEntry(BaseModel):
    id: str
    symbol: str
    strategy_name: str
    action: SignalAction
    opportunity_score: float
    reasons: list[str]
    suggested_quantity: float | None
    risk_reward_ratio: float | None
    created_at: datetime

    class Config:
        from_attributes = True


class SystemLogResponse(BaseModel):
    id: int
    level: str
    service: str
    message: str
    context: dict
    occurred_at: datetime

    class Config:
        from_attributes = True


class BotEventResponse(BaseModel):
    id: int
    action: BotEventAction
    performed_by: str
    reason: str | None
    context: dict
    occurred_at: datetime

    class Config:
        from_attributes = True


@router.get("/decisions", response_model=list[DecisionLogEntry])
def decision_log(
    symbol: str | None = None,
    only_actionable: bool = False,
    limit: int = Query(200, le=1000),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[Signal]:
    query = db.query(Signal)
    if symbol:
        query = query.filter(Signal.symbol == symbol.upper())
    if only_actionable:
        query = query.filter(Signal.action.in_([SignalAction.BUY, SignalAction.SELL]))
    return query.order_by(Signal.created_at.desc()).limit(limit).all()


@router.get("/system", response_model=list[SystemLogResponse])
def system_logs(
    service: str | None = None, level: str | None = None, limit: int = Query(200, le=1000),
    db: Session = Depends(get_db), _: User = Depends(get_current_user),
) -> list[SystemLog]:
    query = db.query(SystemLog)
    if service:
        query = query.filter(SystemLog.service == service)
    if level:
        query = query.filter(SystemLog.level == level.upper())
    return query.order_by(SystemLog.occurred_at.desc()).limit(limit).all()


@router.get("/bot-events", response_model=list[BotEventResponse])
def bot_events(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[BotEvent]:
    return db.query(BotEvent).order_by(BotEvent.occurred_at.desc()).limit(200).all()
