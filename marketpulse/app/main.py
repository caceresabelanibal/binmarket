from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import seed
from .api_routes import router as api_router
from .auth_routes import router as auth_router
from .dashboard import router as dashboard_router
from .scheduler import run_forever

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("marketpulse.main")

_stop_event = asyncio.Event()


@asynccontextmanager
async def lifespan(app: FastAPI):
    seed.run()
    task = asyncio.create_task(run_forever(_stop_event))
    logger.info("MarketPulse started - background ingest/prediction loop running")
    yield
    _stop_event.set()
    task.cancel()


app = FastAPI(title="MarketPulse", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
app.include_router(auth_router)
app.include_router(api_router)
app.include_router(dashboard_router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
