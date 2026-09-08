from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import get_app_settings, get_current_user, get_db
from app.redis_client import redis_client
from binmarket_shared.constants import TIMEFRAMES as VALID_TIMEFRAMES
from binmarket_shared.db.models import AppSettings, Candle, Symbol, SyncJob, SyncStatus, User
from binmarket_shared.redis_keys import (
    BACKFILL_QUEUE_KEY,
    BANDWIDTH_CATEGORIES,
    bandwidth_bucket_key,
    orderbook_top_key,
    ticker_key,
)

router = APIRouter(prefix="/api/market", tags=["market"])


class CandleResponse(BaseModel):
    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    class Config:
        from_attributes = True


class BackfillRequest(BaseModel):
    symbol: str
    timeframe: str
    start_date: datetime | None = None
    end_date: datetime | None = None


class SyncJobResponse(BaseModel):
    id: str
    symbol: str
    timeframe: str
    status: SyncStatus
    candles_synced: int
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


@router.get("/candles", response_model=list[CandleResponse])
def get_candles(
    symbol: str,
    timeframe: str,
    limit: int = Query(500, le=2000),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[Candle]:
    rows = (
        db.query(Candle)
        .filter(Candle.symbol == symbol.upper(), Candle.timeframe == timeframe)
        .order_by(Candle.open_time.desc())
        .limit(limit)
        .all()
    )
    rows.reverse()
    return rows


@router.post("/backfill", response_model=SyncJobResponse)
def request_backfill(
    payload: BackfillRequest, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> SyncJob:
    if payload.timeframe not in VALID_TIMEFRAMES:
        raise ValueError(f"timeframe debe ser uno de {VALID_TIMEFRAMES}")

    job = SyncJob(
        symbol=payload.symbol.upper(), timeframe=payload.timeframe, status=SyncStatus.PENDING,
        range_start=payload.start_date, range_end=payload.end_date or datetime.now(timezone.utc),
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    redis_client.rpush(BACKFILL_QUEUE_KEY, json.dumps({
        "job_id": job.id,
        "symbol": job.symbol,
        "timeframe": job.timeframe,
        "start": job.range_start.isoformat() if job.range_start else None,
        "end": job.range_end.isoformat() if job.range_end else None,
    }))
    return job


@router.get("/backfill/jobs", response_model=list[SyncJobResponse])
def list_backfill_jobs(
    symbol: str | None = None, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> list[SyncJob]:
    query = db.query(SyncJob)
    if symbol:
        query = query.filter(SyncJob.symbol == symbol.upper())
    return query.order_by(SyncJob.created_at.desc()).limit(50).all()


@router.get("/backfill/jobs/{job_id}", response_model=SyncJobResponse)
def get_backfill_job(job_id: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> SyncJob:
    job = db.get(SyncJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job de sincronización no encontrado")
    return job


@router.get("/backfill/queue-length")
def backfill_queue_length(_: User = Depends(get_current_user)) -> dict:
    """How many backfill jobs are still waiting behind the one currently
    running — lets the UI explain "your download is queued", not stuck."""
    return {"pending_in_queue": redis_client.llen(BACKFILL_QUEUE_KEY)}


@router.get("/orderbook")
def get_orderbook_top(symbol: str, _: User = Depends(get_current_user)) -> dict:
    raw = redis_client.get(orderbook_top_key(symbol.upper()))
    return json.loads(raw) if raw else {"bid": None, "ask": None}


@router.get("/ticker")
def get_ticker(symbol: str, _: User = Depends(get_current_user)) -> dict:
    raw = redis_client.get(ticker_key(symbol.upper()))
    return json.loads(raw) if raw else {}


@router.get("/bandwidth")
def get_bandwidth(
    app_settings: AppSettings = Depends(get_app_settings), db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> dict:
    """Measured (not estimated) WebSocket bandwidth from market-data's
    Binance connection, broken down by category, using the most recently
    completed full minute so the rate isn't skewed by a partial one."""
    now = datetime.now(timezone.utc)
    bucket = (now - timedelta(minutes=1)).strftime("%Y%m%d%H%M")

    categories: dict[str, dict] = {}
    total_bytes = 0
    for category in BANDWIDTH_CATEGORIES:
        raw = redis_client.get(bandwidth_bucket_key(category, bucket))
        bytes_per_min = int(raw) if raw else 0
        total_bytes += bytes_per_min
        categories[category] = {"bytes_per_min": bytes_per_min, "kb_per_sec": round(bytes_per_min / 60 / 1024, 3)}

    selected_count = db.query(Symbol).filter(Symbol.is_selected.is_(True)).count()
    timeframes_streamed = len(VALID_TIMEFRAMES) if app_settings.stream_all_timeframes else 2  # 1h + 5m
    streams_per_symbol = 2 + timeframes_streamed  # ticker + depth + klines

    return {
        "measured_minute": bucket,
        "categories": categories,
        "total_bytes_per_min": total_bytes,
        "total_kb_per_sec": round(total_bytes / 60 / 1024, 3),
        "estimated_mb_per_hour": round(total_bytes * 60 / 1024 / 1024, 2),
        "selected_symbols_count": selected_count,
        "streams_per_symbol": streams_per_symbol,
        "total_streams": selected_count * streams_per_symbol,
        "stream_all_timeframes": app_settings.stream_all_timeframes,
        "orderbook_update_speed_ms": app_settings.orderbook_update_speed_ms,
    }
