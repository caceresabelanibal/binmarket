"""The API another bot (e.g. BinMarket) reads. `/api/v1/outlook` is the one
endpoint meant for machine consumption - a plain JSON directional call,
always with the reasoning behind it so a caller (or a human auditing the
caller) never has to trust a bare LONG/SHORT/NO_TRADE blindly.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .auth_routes import get_current_user
from .backtest import evaluate_predictions, summarize_verdicts
from .config import settings
from .db import get_db
from .models import HistoricalEvent, NewsArticle, Prediction, User
from .predictor import generate_prediction, score_to_direction
from .tickers import detect_ticker

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


@router.get("/outlook", response_model=OutlookResponse)
def outlook(fresh: bool = False, db: Session = Depends(get_db)) -> OutlookResponse:
    """The latest stored prediction for the configured primary symbol -
    meant to be polled by another system. Set `fresh=true` to force a brand
    new computation right now instead of returning the last scheduled one
    (useful for testing, costs a handful of HTTP calls to free sources)."""
    if fresh:
        result = generate_prediction(db, settings.primary_symbol)
        from .predictor import persist_prediction

        row = persist_prediction(db, settings.primary_symbol, 48, result)
    else:
        row = (
            db.query(Prediction)
            .filter(Prediction.symbol == settings.primary_symbol)
            .order_by(Prediction.created_at.desc())
            .first()
        )
        if row is None:
            result = generate_prediction(db, settings.primary_symbol)
            from .predictor import persist_prediction

            row = persist_prediction(db, settings.primary_symbol, 48, result)

    return OutlookResponse(
        symbol=row.symbol, symbol_label=settings.primary_symbol_label,
        as_of=row.created_at.isoformat(), horizon_hours=row.horizon_hours,
        direction=row.direction, confidence_pct=row.confidence_pct, sentiment_score=row.sentiment_score,
        article_count=row.reasoning.get("article_count", 0), recent_trend_pct=row.reasoning.get("recent_trend_pct"),
        reasoning=row.reasoning,
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


@router.get("/news", response_model=list[NewsItemResponse])
def recent_news(limit: int = 40, db: Session = Depends(get_db)) -> list[NewsItemResponse]:
    rows = db.query(NewsArticle).order_by(NewsArticle.fetched_at.desc()).limit(min(limit, 150)).all()
    return [
        NewsItemResponse(
            title=r.title, url=r.url, source=r.source, sentiment_score=r.sentiment_score,
            matched_categories=r.matched_categories or [],
            published_at=r.published_at.isoformat() if r.published_at else None,
            ticker=detect_ticker(f"{r.title}. {r.summary or ''}", settings.primary_symbol),
            article_prediction=score_to_direction(r.sentiment_score),
        )
        for r in rows
    ]


class HistoricalEventResponse(BaseModel):
    title: str
    category: str
    event_date: str
    description: str
    market_move_1d_pct: float | None
    market_move_5d_pct: float | None
    source_note: str


@router.get("/analogues", response_model=list[HistoricalEventResponse])
def historical_analogues(db: Session = Depends(get_db)) -> list[HistoricalEventResponse]:
    rows = db.query(HistoricalEvent).order_by(HistoricalEvent.event_date.desc()).all()
    return [
        HistoricalEventResponse(
            title=r.title, category=r.category, event_date=r.event_date.date().isoformat(),
            description=r.description, market_move_1d_pct=r.market_move_1d_pct,
            market_move_5d_pct=r.market_move_5d_pct, source_note=r.source_note,
        )
        for r in rows
    ]


@router.get("/backtest")
def backtest(db: Session = Depends(get_db)) -> dict:
    verdicts = evaluate_predictions(db, settings.primary_symbol)
    return {
        "summary": summarize_verdicts(verdicts),
        "predictions": [v.__dict__ for v in verdicts],
    }


@router.post("/ingest-now")
def trigger_ingest_now(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict:
    """Manual trigger for the dashboard's "Actualizar ahora" button - runs
    one full cycle synchronously instead of waiting for the scheduler."""
    from .ingest import ingest_all_feeds, refresh_price_cache
    from .predictor import persist_prediction

    inserted = ingest_all_feeds(db)
    refresh_price_cache(db, settings.primary_symbol)
    result = generate_prediction(db, settings.primary_symbol)
    row = persist_prediction(db, settings.primary_symbol, 48, result)
    return {"inserted_articles": inserted, "prediction_id": row.id, "direction": row.direction}
