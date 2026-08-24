from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from binmarket_shared.config import settings
from binmarket_shared.logging_utils import configure_logging

from app.routers import (
    auth,
    backtests,
    binance,
    health,
    logs,
    manual_trading,
    market,
    orders,
    portfolio,
    positions,
    risk,
    settings as settings_router,
    signals,
    strategies,
    symbols,
    ws,
)

configure_logging("backend")
logger = logging.getLogger("binmarket.backend")

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="BinMarket API", version="0.1.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(settings_router.router)
app.include_router(binance.router)
app.include_router(symbols.router)
app.include_router(market.router)
app.include_router(signals.router)
app.include_router(orders.router)
app.include_router(positions.router)
app.include_router(manual_trading.router)
app.include_router(backtests.router)
app.include_router(strategies.router)
app.include_router(risk.router)
app.include_router(logs.router)
app.include_router(portfolio.router)
app.include_router(ws.router)


@app.on_event("startup")
async def on_startup() -> None:
    logger.info("BinMarket backend starting up (env=%s, binance_environment=%s)", settings.app_env, settings.binance_environment)
