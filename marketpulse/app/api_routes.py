"""The API another bot (e.g. BinMarket) reads. `/api/v1/outlook` and
`/api/v1/outlooks` are meant for machine consumption - a plain JSON
directional call, always with the reasoning behind it so a caller (or a
human auditing the caller) never has to trust a bare LONG/SHORT/NO_TRADE
blindly.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .auth_routes import get_current_user
from .backtest import evaluate_predictions, summarize_verdicts
from .config import settings
from .db import get_db
from .events_backfill import backfill_pending_event_moves
from .ingest import ingest_all_feeds, prune_old_data, refresh_price_cache
from .learning import DEFAULT_WEIGHTS, update_weights_if_due
from .models import HistoricalEvent, NewsArticle, Prediction, User, WeightAdjustment
from .predictor import (
    PREDICTION_HORIZON_HOURS,
    generate_all_predictions,
    generate_prediction_for_symbol,
    persist_prediction,
    score_to_direction,
)
from .tickers import detect_ticker, label_for_ticker

router = APIRouter(prefix="/api/v1", tags=["marketpulse"])


class OutlookResponse(BaseModel):
    symbol: str
    symbol_label: str
    as_of: str
    horizon_hours: int
    direction: str
    confidence_pct: float
    sentiment_score: float
    article_count: int
    recent_trend_pct: float | None
    reasoning: dict

    class Config:
        from_attributes = True


def _to_outlook_response(row: Prediction) -> OutlookResponse:
    label = settings.primary_symbol_label if row.symbol == settings.primary_symbol else label_for_ticker(row.symbol)
    return OutlookResponse(
        symbol=row.symbol, symbol_label=label,
        as_of=row.created_at.isoformat(), horizon_hours=row.horizon_hours,
        direction=row.direction, confidence_pct=row.confidence_pct, sentiment_score=row.sentiment_score,
        article_count=row.reasoning.get("article_count", 0), recent_trend_pct=row.reasoning.get("recent_trend_pct"),
        reasoning=row.reasoning,
    )


@router.get("/outlook", response_model=OutlookResponse)
def outlook(symbol: str | None = None, fresh: bool = False, db: Session = Depends(get_db)) -> OutlookResponse:
    """The latest stored prediction for `symbol` (defaults to the configured
    primary symbol) - meant to be polled by another system. Set
    `fresh=true` to force a brand new computation right now instead of
    returning the last scheduled one (useful for testing, costs a handful
    of HTTP calls to free sources)."""
    target_symbol = symbol or settings.primary_symbol

    if fresh:
        result = generate_prediction_for_symbol(db, target_symbol)
        row = persist_prediction(db, target_symbol, PREDICTION_HORIZON_HOURS, result)
    else:
        row = (
            db.query(Prediction)
            .filter(Prediction.symbol == target_symbol)
            .order_by(Prediction.created_at.desc())
            .first()
        )
        if row is None:
            result = generate_prediction_for_symbol(db, target_symbol)
            row = persist_prediction(db, target_symbol, PREDICTION_HORIZON_HOURS, result)

    return _to_outlook_response(row)


class PaginatedOutlooksResponse(BaseModel):
    items: list[OutlookResponse]
    total: int
    page: int
    page_size: int


@router.get("/outlooks", response_model=PaginatedOutlooksResponse)
def all_outlooks(
    page: int = 1, page_size: int = 5,
    ticker: str | None = None, direction: str | None = None,
    db: Session = Depends(get_db),
) -> PaginatedOutlooksResponse:
    """The latest stored prediction for EVERY ticker MarketPulse currently
    tracks (requested directly by the user: predict every real ticker the
    news actually names, not just one configured index) - one row per
    distinct symbol, most recent first by confidence. Paginated (5 per page
    by default) with optional `ticker` (substring match against the symbol
    or its display label) and `direction` filters, also requested directly
    by the user so a growing ticker list doesn't turn into one giant page."""
    recent_cutoff_days = 2  # comfortably covers at least a few ingest cycles
    cutoff = datetime.now(timezone.utc) - timedelta(days=recent_cutoff_days)
    rows = (
        db.query(Prediction)
        .filter(Prediction.created_at >= cutoff)
        .order_by(Prediction.created_at.desc())
        .all()
    )
    latest_per_symbol: dict[str, Prediction] = {}
    for row in rows:
        if row.symbol not in latest_per_symbol:
            latest_per_symbol[row.symbol] = row

    responses = [_to_outlook_response(row) for row in latest_per_symbol.values()]

    if ticker:
        needle = ticker.strip().upper()
        responses = [r for r in responses if needle in r.symbol.upper() or needle in r.symbol_label.upper()]
    if direction:
        responses = [r for r in responses if r.direction == direction.strip().upper()]

    responses.sort(key=lambda r: r.confidence_pct, reverse=True)

    page = max(page, 1)
    page_size = max(1, min(page_size, 100))
    total = len(responses)
    start = (page - 1) * page_size
    return PaginatedOutlooksResponse(
        items=responses[start:start + page_size], total=total, page=page, page_size=page_size,
    )


class NewsItemResponse(BaseModel):
    title: str
    url: str
    source: str
    sentiment_score: float
    matched_categories: list
    published_at: str | None
    # Which real ticker this specific article's own sentiment score would
    # apply a prediction to, and what that single-article call would be
    # (LONG/SHORT/NO_TRADE) - both derived live from the article's actual
    # stored title/summary/sentiment_score, judged by the exact same
    # threshold the main blended prediction uses (predictor.DIRECTION_THRESHOLD).
    # Never a separate/invented number - see app/tickers.py's docstring.
    ticker: str
    article_prediction: str

    class Config:
        from_attributes = True


# How many of the most recent articles are even considered for this panel's
# filter/pagination - a display cap, not the real retention window (see
# ingest.NEWS_ARTICLE_RETENTION_DAYS). `ticker`/`article_prediction` are
# derived per-article, not stored columns, so filtering happens in Python
# after this bounded fetch - same approach as /outlooks.
NEWS_DISPLAY_CAP = 500


class PaginatedNewsResponse(BaseModel):
    items: list[NewsItemResponse]
    total: int
    page: int
    page_size: int


@router.get("/news", response_model=PaginatedNewsResponse)
def recent_news(
    ticker: str | None = None, direction: str | None = None,
    page: int = 1, page_size: int = 3,
    db: Session = Depends(get_db),
) -> PaginatedNewsResponse:
    """Paginated (3 per page by default) with optional `ticker` and
    `direction` filters, requested directly by the user so this list - which
    can run into the hundreds within a day - doesn't turn into one giant
    unfiltered page either."""
    rows = db.query(NewsArticle).order_by(NewsArticle.fetched_at.desc()).limit(NEWS_DISPLAY_CAP).all()
    items = [
        NewsItemResponse(
            title=r.title, url=r.url, source=r.source, sentiment_score=r.sentiment_score,
            matched_categories=r.matched_categories or [],
            published_at=r.published_at.isoformat() if r.published_at else None,
            ticker=detect_ticker(r.title, r.summary or "", settings.primary_symbol),
            article_prediction=score_to_direction(r.sentiment_score),
        )
        for r in rows
    ]

    if ticker:
        needle = ticker.strip().upper()
        items = [i for i in items if needle in i.ticker.upper()]
    if direction:
        wanted = direction.strip().upper()
        items = [i for i in items if i.article_prediction == wanted]

    page = max(page, 1)
    page_size = max(1, min(page_size, 100))
    total = len(items)
    start = (page - 1) * page_size
    return PaginatedNewsResponse(
        items=items[start:start + page_size], total=total, page=page, page_size=page_size,
    )


class HistoricalEventResponse(BaseModel):
    title: str
    category: str
    event_date: str
    description: str
    market_move_1d_pct: float | None
    market_move_5d_pct: float | None
    source_note: str


class PaginatedHistoricalEventsResponse(BaseModel):
    items: list[HistoricalEventResponse]
    total: int
    page: int
    page_size: int


@router.get("/analogues", response_model=PaginatedHistoricalEventsResponse)
def historical_analogues(
    date_from: str | None = None, date_to: str | None = None,
    page: int = 1, page_size: int = 3,
    db: Session = Depends(get_db),
) -> PaginatedHistoricalEventsResponse:
    """The curated reference-event table (requested directly by the user: it
    had too few events to be a useful reference, so it was expanded, and
    this list should paginate - 3 per page by default - with an optional
    date range instead of dumping every row onto one long page."""
    query = db.query(HistoricalEvent)
    if date_from:
        query = query.filter(HistoricalEvent.event_date >= datetime.fromisoformat(date_from).replace(tzinfo=timezone.utc))
    if date_to:
        # Inclusive of the whole end date, not just midnight at its start.
        query = query.filter(
            HistoricalEvent.event_date < datetime.fromisoformat(date_to).replace(tzinfo=timezone.utc) + timedelta(days=1)
        )

    page = max(page, 1)
    page_size = max(1, min(page_size, 100))
    total = query.count()
    rows = (
        query.order_by(HistoricalEvent.event_date.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = [
        HistoricalEventResponse(
            title=r.title, category=r.category, event_date=r.event_date.date().isoformat(),
            description=r.description, market_move_1d_pct=r.market_move_1d_pct,
            market_move_5d_pct=r.market_move_5d_pct, source_note=r.source_note,
        )
        for r in rows
    ]
    return PaginatedHistoricalEventsResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/backtest")
def backtest(
    ticker: str | None = None, verdict: str | None = None,
    date_from: str | None = None, date_to: str | None = None,
    page: int = 1, page_size: int = 5,
    db: Session = Depends(get_db),
) -> dict:
    """Scores every ticker MarketPulse has predictions for, then applies
    whatever filters are given (requested directly by the user: search by
    ticker, by date, by result) before paginating (5 per page by default).
    `summary` is computed over the full FILTERED set, not just the current
    page, so the hit rate shown always matches what's actually being
    looked at - filter to one ticker and the stats become that ticker's
    own real track record, not the page-slice's.

    `ticker`/date range are pushed down into the SQL query (evaluate_predictions)
    rather than pulled into Python first - at 40+ tickers x a 30-min cadence
    this table grows fast, and a date search should reach further back than
    the normal 14-day default, not be silently capped by it.
    """
    date_from_dt = datetime.fromisoformat(date_from).replace(tzinfo=timezone.utc) if date_from else None
    # Inclusive of the whole end date, not just midnight at its start.
    date_to_dt = (
        datetime.fromisoformat(date_to).replace(tzinfo=timezone.utc) + timedelta(days=1) if date_to else None
    )

    verdicts = evaluate_predictions(db, symbol=ticker, date_from=date_from_dt, date_to=date_to_dt)

    if verdict:
        wanted = verdict.strip().upper()
        verdicts = [v for v in verdicts if v.verdict == wanted]

    summary = summarize_verdicts(verdicts)

    page = max(page, 1)
    page_size = max(1, min(page_size, 100))
    total = len(verdicts)
    start = (page - 1) * page_size
    page_items = verdicts[start:start + page_size]

    return {
        "summary": summary,
        "predictions": {
            "items": [v.__dict__ for v in page_items], "total": total, "page": page, "page_size": page_size,
        },
    }


class WeightAdjustmentResponse(BaseModel):
    created_at: str
    news_weight: float
    analogue_weight: float
    trend_weight: float
    news_hit_rate: float | None
    analogue_hit_rate: float | None
    trend_hit_rate: float | None
    sample_size: int
    note: str


class CurrentWeightsResponse(BaseModel):
    news_weight: float
    analogue_weight: float
    trend_weight: float
    is_learned: bool  # false until the very first real adjustment has happened
    last_adjustment: WeightAdjustmentResponse | None


class PaginatedWeightHistoryResponse(BaseModel):
    items: list[WeightAdjustmentResponse]
    total: int
    page: int
    page_size: int


def _to_weight_adjustment_response(row: WeightAdjustment) -> WeightAdjustmentResponse:
    return WeightAdjustmentResponse(
        created_at=row.created_at.isoformat(), news_weight=row.news_weight, analogue_weight=row.analogue_weight,
        trend_weight=row.trend_weight, news_hit_rate=row.news_hit_rate, analogue_hit_rate=row.analogue_hit_rate,
        trend_hit_rate=row.trend_hit_rate, sample_size=row.sample_size, note=row.note,
    )


@router.get("/learning")
def learning_state(page: int = 1, page_size: int = 3, db: Session = Depends(get_db)) -> dict:
    """Requested directly by the user ("me gustaría que vaya aprendiendo"):
    the model's three blend weights (news sentiment / historical analogues /
    recent trend) are periodically nudged by app/learning.py based on each
    component's own real, scored track record - this exposes the weights
    currently in effect plus a full, paginated audit log of every past
    adjustment and the exact hit-rate numbers that justified it, so nothing
    about "the model learning" is a hidden/opaque change."""
    latest = db.query(WeightAdjustment).order_by(WeightAdjustment.created_at.desc()).first()
    current = CurrentWeightsResponse(
        news_weight=latest.news_weight if latest else DEFAULT_WEIGHTS["news"],
        analogue_weight=latest.analogue_weight if latest else DEFAULT_WEIGHTS["analogue"],
        trend_weight=latest.trend_weight if latest else DEFAULT_WEIGHTS["trend"],
        is_learned=latest is not None,
        last_adjustment=_to_weight_adjustment_response(latest) if latest else None,
    )

    page = max(page, 1)
    page_size = max(1, min(page_size, 100))
    total = db.query(WeightAdjustment).count()
    rows = (
        db.query(WeightAdjustment)
        .order_by(WeightAdjustment.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "current": current,
        "history": PaginatedWeightHistoryResponse(
            items=[_to_weight_adjustment_response(r) for r in rows], total=total, page=page, page_size=page_size,
        ),
    }


@router.post("/ingest-now")
def trigger_ingest_now(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict:
    """Manual trigger for the dashboard's "Actualizar ahora" button - runs
    one full cycle synchronously instead of waiting for the scheduler, for
    every ticker currently in the news (not just the primary symbol)."""
    inserted = ingest_all_feeds(db)
    prune_old_data(db)
    backfill_pending_event_moves(db)
    update_weights_if_due(db)

    results = generate_all_predictions(db)
    for sym in results:
        refresh_price_cache(db, sym)

    predictions = {
        sym: persist_prediction(db, sym, PREDICTION_HORIZON_HOURS, result) for sym, result in results.items()
    }
    primary_row = predictions.get(settings.primary_symbol)

    return {
        "inserted_articles": inserted,
        "tickers_predicted": len(predictions),
        "prediction_id": primary_row.id if primary_row else None,
        "direction": primary_row.direction if primary_row else None,
    }
