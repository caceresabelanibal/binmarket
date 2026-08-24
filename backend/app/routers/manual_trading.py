from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import get_app_settings, get_current_user, get_db
from app.redis_client import redis_client
from binmarket_shared.binance.filters import SymbolFilters
from binmarket_shared.db.models import AppSettings, Position, PositionStatus, Symbol, User
from binmarket_shared.quant.costs import estimate_spread_pct, estimate_trade_economics
from binmarket_shared.redis_keys import orderbook_top_key, ticker_key
from binmarket_shared.trading.execution import get_execution_provider
from binmarket_shared.trading.orders.manager import OrderManager
from binmarket_shared.trading.risk.manager import RiskManager

router = APIRouter(prefix="/api/manual-trading", tags=["manual-trading"])


class ManualBuyRequest(BaseModel):
    symbol: str
    percent_of_balance: float | None = None
    quantity: float | None = None
    stop_loss_pct: float | None = 3.0
    take_profit_pct: float | None = 6.0
    idempotency_key: str | None = None


class ManualSellRequest(BaseModel):
    position_id: str


class PreviewResponse(BaseModel):
    symbol: str
    side: str
    reference_price: float
    quantity: float
    estimated_notional: float
    estimated_fee: float
    spread_pct: float
    stop_loss_price: float | None
    take_profit_price: float | None
    estimated_risk_usdt: float | None
    risk_reward_ratio: float | None
    net_profit_pct_if_target_hit: float | None
    risk_check_passed: bool
    risk_check_reason: str | None


def _current_price_and_book(symbol: str) -> tuple[float, float | None, float | None]:
    raw = redis_client.get(ticker_key(symbol))
    if not raw:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"No hay precio en caché para {symbol}; esperar a que market-data lo publique")
    price = float(json.loads(raw)["price"])
    book_raw = redis_client.get(orderbook_top_key(symbol))
    bid = ask = None
    if book_raw:
        book = json.loads(book_raw)
        bid, ask = float(book["bid"]), float(book["ask"])
    return price, bid, ask


def _build_execution_provider(app_settings: AppSettings, db: Session):
    from app.core.binance_factory import get_binance_client_for_mode

    if app_settings.mode.value == "PAPER":
        return get_execution_provider("PAPER", db=db, redis_client=redis_client)
    client = get_binance_client_for_mode(app_settings.mode)
    return get_execution_provider(app_settings.mode.value, binance_client=client)


def _symbol_filters(db: Session, symbol: str) -> SymbolFilters | None:
    row = db.query(Symbol).filter(Symbol.symbol == symbol.upper()).one_or_none()
    if row is None or row.lot_step_size <= 0:
        return None
    return SymbolFilters(symbol, row.price_tick_size, row.lot_step_size, row.min_qty, row.max_qty, row.min_notional)


def _resolve_buy_preview(
    payload: ManualBuyRequest, db: Session, app_settings: AppSettings
) -> tuple[PreviewResponse, float]:
    symbol = payload.symbol.upper()
    price, bid, ask = _current_price_and_book(symbol)

    provider = _build_execution_provider(app_settings, db)
    available_capital = provider.get_available_balance("USDT")

    if payload.quantity:
        quantity = payload.quantity
    elif payload.percent_of_balance:
        quantity = (available_capital * payload.percent_of_balance / 100) / price
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Especificar `quantity` o `percent_of_balance`")

    symbol_filters = _symbol_filters(db, symbol)
    if symbol_filters:
        quantity = symbol_filters.round_quantity(quantity)

    stop_loss_price = price * (1 - (payload.stop_loss_pct or 0) / 100) if payload.stop_loss_pct else None
    take_profit_price = price * (1 + (payload.take_profit_pct or 0) / 100) if payload.take_profit_pct else None

    spread_pct = estimate_spread_pct(bid or price, ask or price)
    economics = None
    if take_profit_price:
        economics = estimate_trade_economics(
            price, take_profit_price, stop_loss_price, app_settings.taker_fee_pct, spread_pct,
            app_settings.default_slippage_pct,
        )

    notional = quantity * price
    fee = notional * (app_settings.taker_fee_pct / 100)
    risk_amount = (price - stop_loss_price) * quantity if stop_loss_price else None

    risk_manager = RiskManager(db, app_settings)
    risk_check = risk_manager.check_manual_entry(notional, available_capital, app_settings.mode)

    preview = PreviewResponse(
        symbol=symbol, side="BUY", reference_price=price, quantity=quantity, estimated_notional=notional,
        estimated_fee=fee, spread_pct=spread_pct, stop_loss_price=stop_loss_price, take_profit_price=take_profit_price,
        estimated_risk_usdt=risk_amount, risk_reward_ratio=economics.risk_reward_ratio if economics else None,
        net_profit_pct_if_target_hit=economics.net_profit_pct if economics else None,
        risk_check_passed=risk_check.allowed, risk_check_reason=risk_check.reason,
    )
    return preview, quantity


@router.post("/buy/preview", response_model=PreviewResponse)
def preview_buy(
    payload: ManualBuyRequest, db: Session = Depends(get_db), app_settings: AppSettings = Depends(get_app_settings),
    _: User = Depends(get_current_user),
) -> PreviewResponse:
    preview, _quantity = _resolve_buy_preview(payload, db, app_settings)
    return preview


@router.post("/buy/confirm")
def confirm_buy(
    payload: ManualBuyRequest, db: Session = Depends(get_db), app_settings: AppSettings = Depends(get_app_settings),
    user: User = Depends(get_current_user),
) -> dict:
    preview, quantity = _resolve_buy_preview(payload, db, app_settings)
    if not preview.risk_check_passed:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Risk Manager rechazó la operación: {preview.risk_check_reason}")

    provider = _build_execution_provider(app_settings, db)
    order_manager = OrderManager(db, provider, redis_client)

    idempotency_key = payload.idempotency_key or str(uuid.uuid4())
    order, position = order_manager.open_manual_position(
        payload.symbol.upper(), quantity, preview.stop_loss_price, preview.take_profit_price,
        app_settings.mode, idempotency_key,
    )
    db.commit()
    return {"order_id": order.id, "position_id": position.id if position else None, "status": order.status.value}


@router.post("/sell/confirm")
def confirm_sell(
    payload: ManualSellRequest, db: Session = Depends(get_db), app_settings: AppSettings = Depends(get_app_settings),
    user: User = Depends(get_current_user),
) -> dict:
    position = db.get(Position, payload.position_id)
    if position is None or position.status != PositionStatus.OPEN:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Posición no encontrada o ya cerrada")

    provider = _build_execution_provider(app_settings, db)
    order_manager = OrderManager(db, provider, redis_client)

    order = order_manager.close_position(position, f"Venta manual por {user.username}", app_settings.mode, is_manual=True)
    db.commit()
    return {"order_id": order.id, "status": order.status.value, "realized_pnl": position.realized_pnl}
