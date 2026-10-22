"""The prediction engine: combines (1) recency-weighted news sentiment,
(2) historical-analogue priors from matched event categories, and (3) the
recent real price trend into a directional call - LONG / SHORT / NO_TRADE -
for the next `horizon_hours`.

Explicitly optimized to predict DIRECTION, not magnitude, per the user's
own framing: the output is a sign and a confidence, not a target price. The
whole computation is a transparent weighted sum, not a model with hidden
weights - `reasoning` always carries every number and every contributing
article/event that went into the final call, the same "never a black box"
discipline as every strategy in the sibling BinMarket project.

This is a genuinely hard, speculative problem - predicting market direction
from news sentiment has famously weak statistical edge in the academic
literature. This module does not pretend otherwise: it is explicit,
auditable, and meant to be backtested and judged by its real hit rate (see
app/api_routes.py's /backtest endpoint), not trusted on faith.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from .models import HistoricalEvent, NewsArticle, Prediction
from .prices import fetch_daily_closes

NEWS_LOOKBACK_HOURS = 48
ARTICLE_QUERY_SAFETY_CAP = 5000
# Below this |score|, the signal is too weak/mixed to act on - NO_TRADE, not
# a coin-flip LONG or SHORT. Shared with app/tickers.py's per-article call
# (via score_to_direction below) so a single headline's own sentiment score
# is judged by the exact same bar as the blended prediction - no separate,
# looser threshold invented just to make individual articles look more
# decisive than the real aggregate prediction.
DIRECTION_THRESHOLD = 0.08


def score_to_direction(score: float) -> str:
    if score > DIRECTION_THRESHOLD:
        return "LONG"
    if score < -DIRECTION_THRESHOLD:
        return "SHORT"
    return "NO_TRADE"


@dataclass
class ArticleContribution:
    title: str
    url: str
    source: str
    sentiment_score: float
    categories: list[str]
    age_hours: float
    weight: float


@dataclass
class AnalogueMatch:
    title: str
    category: str
    event_date: str
    market_move_1d_pct: float | None
    market_move_5d_pct: float | None


@dataclass
class PredictionResult:
    direction: str
    confidence_pct: float
    sentiment_score: float
    news_component: float
    analogue_component: float
    trend_component: float
    contributing_articles: list[ArticleContribution]
    analogues: list[AnalogueMatch]
    recent_trend_pct: float | None
    article_count: int


def _recency_weight(age_hours: float) -> float:
    """Linear decay to zero at NEWS_LOOKBACK_HOURS - a 1-hour-old headline
    counts far more than a 47-hour-old one."""
    return max(0.0, 1.0 - age_hours / NEWS_LOOKBACK_HOURS)


def _recent_trend_pct(symbol: str) -> float | None:
    closes = fetch_daily_closes(symbol, days_back=5)
    if len(closes) < 2:
        return None
    first, last = closes[0][1], closes[-1][1]
    if not first:
        return None
    return (last - first) / first * 100


def generate_prediction(db: Session, symbol: str, horizon_hours: int = 48) -> PredictionResult:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=NEWS_LOOKBACK_HOURS)
    articles = (
        db.query(NewsArticle)
        .filter(NewsArticle.fetched_at >= cutoff)
        .order_by(NewsArticle.fetched_at.desc())
        # Real production bug: an earlier .limit(300) silently truncated this
        # once real volume grew past it (confirmed 1,421 real articles in a
        # 48h window within days of deployment), making "article_count" look
        # permanently stuck and hiding real growth from the dashboard. This
        # cap is now a generous safety net, not the expected ceiling - fetched_at
        # is indexed, so a few thousand rows is still cheap.
        .limit(ARTICLE_QUERY_SAFETY_CAP)
        .all()
    )

    now = datetime.now(timezone.utc)
    contributions: list[ArticleContribution] = []
    weighted_sum = 0.0
    weight_total = 0.0
    category_hits: dict[str, int] = {}

    for a in articles:
        ref_time = a.published_at or a.fetched_at
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=timezone.utc)
        age_hours = max(0.0, (now - ref_time).total_seconds() / 3600)
        weight = _recency_weight(age_hours)
        if weight <= 0:
            continue
        weighted_sum += a.sentiment_score * weight
        weight_total += weight
        for cat in a.matched_categories or []:
            category_hits[cat] = category_hits.get(cat, 0) + 1
        contributions.append(ArticleContribution(
            title=a.title, url=a.url, source=a.source, sentiment_score=a.sentiment_score,
            categories=a.matched_categories or [], age_hours=round(age_hours, 1), weight=round(weight, 3),
        ))

    news_sentiment = (weighted_sum / weight_total) if weight_total > 0 else 0.0

    # Historical analogues: for every category trending in the current news
    # (at least 2 matching articles, to avoid a single stray headline
    # dragging in an unrelated historical event), pull matching
    # HistoricalEvent rows and average their 1-day reaction as a prior.
    trending_categories = [cat for cat, count in category_hits.items() if count >= 2]
    analogue_rows: list[HistoricalEvent] = []
    if trending_categories:
        analogue_rows = (
            db.query(HistoricalEvent)
            .filter(HistoricalEvent.category.in_(trending_categories))
            .all()
        )
    analogue_moves = [e.market_move_1d_pct for e in analogue_rows if e.market_move_1d_pct is not None]
    analogue_prior = (sum(analogue_moves) / len(analogue_moves) / 10) if analogue_moves else 0.0
    # /10 rescales a typical event-day % move (often single digits, COVID
    # being a deliberate outlier) into roughly the same -1..+1 range as the
    # sentiment score, so neither component dominates the blend by units
    # alone.
    analogue_prior = max(-1.0, min(1.0, analogue_prior))

    analogues = [
        AnalogueMatch(
            title=e.title, category=e.category, event_date=e.event_date.date().isoformat(),
            market_move_1d_pct=e.market_move_1d_pct, market_move_5d_pct=e.market_move_5d_pct,
        )
        for e in analogue_rows
    ]

    trend_pct = _recent_trend_pct(symbol)
    trend_component = max(-1.0, min(1.0, (trend_pct or 0.0) / 5))  # a 5% 5-day move maxes this out

    # Weights: news sentiment is the primary signal (it's the freshest,
    # most specific-to-right-now input); historical analogues and recent
    # trend are secondary confirmation/context, not drivers on their own.
    combined = news_sentiment * 0.55 + analogue_prior * 0.25 + trend_component * 0.20
    direction = score_to_direction(combined)

    # Confidence scales with |combined| AND how much real news volume backs
    # it - a strong score from 2 articles is less trustworthy than the same
    # score from 40.
    volume_factor = min(1.0, len(contributions) / 20)
    confidence_pct = round(min(95.0, abs(combined) * 100 * (0.5 + 0.5 * volume_factor)), 1)

    contributions.sort(key=lambda c: abs(c.sentiment_score) * c.weight, reverse=True)

    return PredictionResult(
        direction=direction,
        confidence_pct=confidence_pct,
        sentiment_score=round(news_sentiment, 4),
        news_component=round(news_sentiment * 0.55, 4),
        analogue_component=round(analogue_prior * 0.25, 4),
        trend_component=round(trend_component * 0.20, 4),
        contributing_articles=contributions[:15],
        analogues=analogues,
        recent_trend_pct=round(trend_pct, 2) if trend_pct is not None else None,
        article_count=len(contributions),
    )


def persist_prediction(db: Session, symbol: str, horizon_hours: int, result: PredictionResult) -> Prediction:
    reasoning = {
        "news_component": result.news_component,
        "analogue_component": result.analogue_component,
        "trend_component": result.trend_component,
        "recent_trend_pct": result.recent_trend_pct,
        "article_count": result.article_count,
        "contributing_articles": [
            {
                "title": c.title, "url": c.url, "source": c.source,
                "sentiment_score": c.sentiment_score, "categories": c.categories,
                "age_hours": c.age_hours, "weight": c.weight,
            }
            for c in result.contributing_articles
        ],
        "historical_analogues": [
            {
                "title": a.title, "category": a.category, "event_date": a.event_date,
                "market_move_1d_pct": a.market_move_1d_pct, "market_move_5d_pct": a.market_move_5d_pct,
            }
            for a in result.analogues
        ],
    }
    row = Prediction(
        symbol=symbol, horizon_hours=horizon_hours, direction=result.direction,
        confidence_pct=result.confidence_pct, sentiment_score=result.sentiment_score, reasoning=reasoning,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
