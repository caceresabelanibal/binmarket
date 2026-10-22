from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from sqlalchemy import delete
from sqlalchemy.orm import Session

from .feeds import FEEDS, fetch_feed
from .models import MarketPriceDaily, NewsArticle, Prediction
from .prices import fetch_daily_closes
from .sentiment import score_text

logger = logging.getLogger("marketpulse.ingest")

# Real production incident this heads off: news_articles reached 2,041 rows
# within 3 days of deployment with no retention at all, which is exactly
# what made generate_prediction's old hardcoded query limit start silently
# truncating real data (see predictor.py). Articles only matter for the
# 48h-lookback prediction anyway; keeping 14 days is generous headroom for
# debugging/review without the table growing forever. Predictions are kept
# much longer (backtest.py's whole point is a long real track record).
NEWS_ARTICLE_RETENTION_DAYS = 14
PREDICTION_RETENTION_DAYS = 180


def _parse_published(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return None


def ingest_all_feeds(db: Session) -> int:
    """Fetches every configured feed, scores and stores genuinely new
    articles (by URL), skips ones already seen. Returns how many new
    articles were inserted. Never raises - a feed outage is logged and
    skipped, never fatal to the ingest cycle."""
    inserted = 0
    for source in FEEDS:
        try:
            items = fetch_feed(source)
        except Exception:
            logger.exception("Feed fetch crashed unexpectedly: %s", source.name)
            continue

        for item in items:
            exists = db.query(NewsArticle.id).filter(NewsArticle.url == item.url).first()
            if exists:
                continue
            scored = score_text(f"{item.title}. {item.summary}")
            db.add(NewsArticle(
                source=source.name, title=item.title, url=item.url, summary=item.summary[:2000],
                published_at=_parse_published(item.published_at),
                sentiment_score=scored.score, matched_categories=scored.categories,
            ))
            inserted += 1
        db.commit()
    return inserted


def refresh_price_cache(db: Session, symbol: str) -> int:
    """Upserts the last 30 real daily closes for `symbol`. Returns how many
    rows were newly inserted (existing dates are left untouched, so a
    historical close is never silently overwritten by a later, different
    source)."""
    closes = fetch_daily_closes(symbol, days_back=30)
    inserted = 0
    for price_date, close in closes:
        exists = (
            db.query(MarketPriceDaily.id)
            .filter(MarketPriceDaily.symbol == symbol, MarketPriceDaily.price_date == datetime.combine(price_date, datetime.min.time(), tzinfo=timezone.utc))
            .first()
        )
        if exists:
            continue
        db.add(MarketPriceDaily(
            symbol=symbol, price_date=datetime.combine(price_date, datetime.min.time(), tzinfo=timezone.utc), close=close,
        ))
        inserted += 1
    db.commit()
    return inserted


def prune_old_data(db: Session) -> tuple[int, int]:
    """No Redis/gate needed here (unlike BinMarket's equivalent) - both
    deletes are cheap, indexed, and idempotent, so running them every
    ingest cycle (every `ingest_interval_minutes`) is simplest and safe."""
    news_cutoff = datetime.now(timezone.utc) - timedelta(days=NEWS_ARTICLE_RETENTION_DAYS)
    prediction_cutoff = datetime.now(timezone.utc) - timedelta(days=PREDICTION_RETENTION_DAYS)

    news_result = db.execute(delete(NewsArticle).where(NewsArticle.fetched_at < news_cutoff))
    prediction_result = db.execute(delete(Prediction).where(Prediction.created_at < prediction_cutoff))
    db.commit()
    return news_result.rowcount or 0, prediction_result.rowcount or 0
