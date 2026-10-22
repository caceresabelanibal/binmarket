"""The prediction engine: combines (1) recency-weighted news sentiment,
(2) historical-analogue priors from matched event categories (boosted when a
historical event is about the SAME ticker), and (3) the recent real price
trend into a directional call - LONG / SHORT / NO_TRADE - for the next
`horizon_hours`.

Tracks every ticker that real news actually names, not just one configured
index (requested directly by the user: "no se la noticia a que ticket le va
a impactar... necesito que mires la noticia, entiendas a que ticket le va a
impactar, y haga la predicción basado en el historial"). `generate_all_predictions`
groups the same 48h article window by the ticker `app/tickers.py` detects
per article, and runs one full blend per ticker with enough real volume
behind it - the configured primary symbol (general/macro news with no
specific company named) is always included, even on a quiet news day, since
that's the main index-level call other systems may depend on.

Explicitly optimized to predict DIRECTION, not magnitude, per the user's own
framing: the output is a sign and a confidence, not a target price. The
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

from .config import settings
from .models import HistoricalEvent, NewsArticle, Prediction
from .prices import fetch_daily_closes
from .tickers import detect_ticker

NEWS_LOOKBACK_HOURS = 48
ARTICLE_QUERY_SAFETY_CAP = 5000
# A ticker needs at least this many real articles in the window before it
# gets its own prediction - one stray headline about a company is not a
# real signal. The configured primary symbol (general/macro news) is exempt
# from this floor - see generate_all_predictions.
MIN_ARTICLES_PER_TICKER = 2
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
    same_ticker: bool


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


def _fetch_recent_articles(db: Session) -> list[NewsArticle]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=NEWS_LOOKBACK_HOURS)
    return (
        db.query(NewsArticle)
        .filter(NewsArticle.fetched_at >= cutoff)
        .order_by(NewsArticle.fetched_at.desc())
        # Real production bug: an earlier .limit(300) silently truncated this
        # once real volume grew past it (confirmed 1,421 real articles in a
        # 48h window within days of deployment), making "article_count" look
        # permanently stuck and hiding real growth from the dashboard. This
        # cap is now a generous safety net, not the expected ceiling -
        # fetched_at is indexed, so a few thousand rows is still cheap.
        .limit(ARTICLE_QUERY_SAFETY_CAP)
        .all()
    )


def group_articles_by_ticker(articles: list[NewsArticle]) -> dict[str, list[NewsArticle]]:
    groups: dict[str, list[NewsArticle]] = {}
    for a in articles:
        ticker = detect_ticker(a.title, a.summary or "", settings.primary_symbol)
        groups.setdefault(ticker, []).append(a)
    return groups


def _blend(db: Session, symbol: str, articles: list[NewsArticle]) -> PredictionResult:
    """Pure-ish computation over an already-filtered article list (grouping
    by ticker/relevance is the caller's job - see generate_all_predictions)
    plus one historical-analogue query scoped to this symbol's own trending
    categories."""
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

    # Historical analogues: for every category trending in this ticker's own
    # news (at least 2 matching articles, to avoid a single stray headline
    # dragging in an unrelated historical event), pull matching
    # HistoricalEvent rows. A row about this EXACT ticker (event.symbol ==
    # symbol) is a much stronger analogue than a same-category-different-
    # company one (e.g. a new Tesla headline recalling the real Tesla
    # Roadster reveal, not just "some product_launch happened once") -
    # counted twice in the average to reflect that, not silently discarded
    # or treated identically to an unrelated company's history.
    trending_categories = [cat for cat, count in category_hits.items() if count >= 2]
    analogue_rows: list[HistoricalEvent] = []
    if trending_categories:
        analogue_rows = (
            db.query(HistoricalEvent)
            .filter(HistoricalEvent.category.in_(trending_categories))
            .all()
        )

    weighted_moves: list[float] = []
    for e in analogue_rows:
        if e.market_move_1d_pct is None:
            continue
        weighted_moves.append(e.market_move_1d_pct)
        if e.symbol == symbol:
            weighted_moves.append(e.market_move_1d_pct)  # same-ticker analogue counts twice

    analogue_prior = (sum(weighted_moves) / len(weighted_moves) / 10) if weighted_moves else 0.0
    # /10 rescales a typical event-day % move (often single digits, COVID
    # being a deliberate outlier) into roughly the same -1..+1 range as the
    # sentiment score, so neither component dominates the blend by units
    # alone.
    analogue_prior = max(-1.0, min(1.0, analogue_prior))

    analogues = [
        AnalogueMatch(
            title=e.title, category=e.category, event_date=e.event_date.date().isoformat(),
            market_move_1d_pct=e.market_move_1d_pct, market_move_5d_pct=e.market_move_5d_pct,
            same_ticker=(e.symbol == symbol),
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


def generate_prediction_for_symbol(db: Session, symbol: str) -> PredictionResult:
    """Single-symbol entry point: filters the recent article window down to
    just the ones whose detected ticker is `symbol`, then blends. Used for
    an on-demand `?fresh=true&symbol=...` outlook request for one ticker."""
    articles = _fetch_recent_articles(db)
    groups = group_articles_by_ticker(articles)
    return _blend(db, symbol, groups.get(symbol, []))


def generate_all_predictions(db: Session) -> dict[str, PredictionResult]:
    """Generates one prediction per real ticker currently in the news (at
    least MIN_ARTICLES_PER_TICKER articles), plus always the configured
    primary symbol (general/macro news with no specific company named) even
    on a quiet day - that's the main index-level call other systems may
    depend on, so it should never simply be missing."""
    articles = _fetch_recent_articles(db)
    groups = group_articles_by_ticker(articles)

    results: dict[str, PredictionResult] = {}
    primary = settings.primary_symbol
    results[primary] = _blend(db, primary, groups.get(primary, []))

    for ticker, ticker_articles in groups.items():
        if ticker == primary:
            continue
        if len(ticker_articles) < MIN_ARTICLES_PER_TICKER:
            continue
        results[ticker] = _blend(db, ticker, ticker_articles)

    return results


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
                "same_ticker": a.same_ticker,
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
