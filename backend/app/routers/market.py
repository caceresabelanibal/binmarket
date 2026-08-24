from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.redis_client import redis_client
from binmarket_shared.constants import TIMEFRAMES as VALID_TIMEFRAMES
from binmarket_shared.db.models import Candle, SyncJob, SyncStatus, User
from binmarket_shared.redis_keys import BACKFILL_QUEUE_KEY, orderbook_top_key, ticker_key

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
