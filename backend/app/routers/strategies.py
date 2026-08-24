from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from binmarket_shared.db.models import Strategy, User
from binmarket_shared.trading.strategies.registry import STRATEGY_REGISTRY

router = APIRouter(prefix="/api/strategies", tags=["strategies"])


class StrategyResponse(BaseModel):
    id: int
    name: str
    version: str
    description: str
    parameters: dict
    is_enabled: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class StrategyUpdateRequest(BaseModel):
    parameters: dict | None = None
    is_enabled: bool | None = None


@router.get("", response_model=list[StrategyResponse])
def list_strategies(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[Strategy]:
    return db.query(Strategy).order_by(Strategy.name).all()


@router.put("/{name}", response_model=StrategyResponse)
def update_strategy(
    name: str, payload: StrategyUpdateRequest, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> Strategy:
    if name not in STRATEGY_REGISTRY:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Estrategia desconocida: {name}")
    row = db.query(Strategy).filter(Strategy.name == name).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Estrategia no encontrada en la base de datos; reiniciar el backend para re-sembrarla")
    if payload.parameters is not None:
        row.parameters = {**row.parameters, **payload.parameters}
    if payload.is_enabled is not None:
        row.is_enabled = payload.is_enabled
    db.commit()
    db.refresh(row)
    return row
