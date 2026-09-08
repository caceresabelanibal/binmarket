from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.binance_factory import get_binance_client_for_mode
from app.core.deps import get_app_settings, get_current_user, get_db
from app.redis_client import redis_client
from binmarket_shared.binance.filters import SymbolFilters
from binmarket_shared.db.models import AppSettings, Symbol, User
from binmarket_shared.redis_keys import ticker_key

router = APIRouter(prefix="/api/symbols", tags=["symbols"])


class SymbolResponse(BaseModel):
    symbol: str
    base_asset: str
    quote_asset: str
    status: str
    is_selected: bool
    is_favorite: bool
    is_auto_selected: bool
    price_tick_size: float
    lot_step_size: float
    min_notional: float
    last_price: float | None = None
    price_change_pct_24h: float | None = None
    volume_24h: float | None = None
    high_24h: float | None = None
    low_24h: float | None = None

    class Config:
        from_attributes = True


class SymbolListResponse(BaseModel):
    items: list[SymbolResponse]
    total: int
    page: int
    page_size: int


class SelectRequest(BaseModel):
    selected: bool


class FavoriteRequest(BaseModel):
    favorite: bool


@router.post("/sync")
def sync_symbols(
    db: Session = Depends(get_db),
    app_settings: AppSettings = Depends(get_app_settings),
    _: User = Depends(get_current_user),
) -> dict:
    """Pulls the full tradeable symbol list + filters from Binance. Always
    reads from production reference data (public endpoint, no key needed)
    since it is the canonical, most complete set — see docs/architecture.md
    on why filters are sourced this way regardless of the active mode."""
    from binmarket_shared.binance.client import BinanceClient

    client = BinanceClient("", "", environment="production")
    try:
        info = client.get_exchange_info()
    finally:
        client.close()

    created, updated = 0, 0
    for s in info.get("symbols", []):
        if s.get("status") != "TRADING":
            continue
        filters = SymbolFilters.from_exchange_info_symbol(s)
        row = db.query(Symbol).filter(Symbol.symbol == s["symbol"]).one_or_none()
        if row is None:
            row = Symbol(symbol=s["symbol"], base_asset=s["baseAsset"], quote_asset=s["quoteAsset"])
            db.add(row)
            created += 1
        else:
            updated += 1
        row.status = s["status"]
        row.price_tick_size = filters.tick_size
        row.lot_step_size = filters.step_size
        row.min_qty = filters.min_qty
        row.max_qty = filters.max_qty
        row.min_notional = filters.min_notional

    db.commit()
    return {"created": created, "updated": updated}


def _merge_live_stats(row: Symbol) -> SymbolResponse:
    response = SymbolResponse.model_validate(row)
    raw = redis_client.get(ticker_key(row.symbol))
    if raw:
        data = json.loads(raw)
        response.last_price = data.get("price")
        response.price_change_pct_24h = data.get("price_change_pct_24h")
        response.volume_24h = data.get("volume_24h")
        response.high_24h = data.get("high_24h")
        response.low_24h = data.get("low_24h")
    return response


@router.get("", response_model=SymbolListResponse)
def list_symbols(
    selected_only: bool = False,
    favorites_only: bool = False,
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> SymbolListResponse:
    query = db.query(Symbol)
    if selected_only:
        query = query.filter(Symbol.is_selected.is_(True))
    if favorites_only:
        query = query.filter(Symbol.is_favorite.is_(True))
    if search:
        query = query.filter(Symbol.symbol.ilike(f"%{search.strip().upper()}%"))

    total = query.with_entities(func.count(Symbol.id)).scalar() or 0
    rows = (
        query.order_by(Symbol.symbol)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return SymbolListResponse(
        items=[_merge_live_stats(r) for r in rows], total=total, page=page, page_size=page_size
    )


@router.post("/{symbol}/select", response_model=SymbolResponse)
def select_symbol(symbol: str, payload: SelectRequest, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> SymbolResponse:
    row = db.query(Symbol).filter(Symbol.symbol == symbol.upper()).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Símbolo no encontrado; ejecutar /symbols/sync primero")
    row.is_selected = payload.selected
    db.commit()
    db.refresh(row)
    return _merge_live_stats(row)


@router.post("/{symbol}/favorite", response_model=SymbolResponse)
def favorite_symbol(symbol: str, payload: FavoriteRequest, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> SymbolResponse:
    row = db.query(Symbol).filter(Symbol.symbol == symbol.upper()).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Símbolo no encontrado")
    row.is_favorite = payload.favorite
    db.commit()
    db.refresh(row)
    return _merge_live_stats(row)
