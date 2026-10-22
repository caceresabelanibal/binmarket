"""Tests for generating one prediction per real ticker currently in the
news (requested directly by the user), not just the one configured primary
symbol.

`fetch_daily_closes` is monkeypatched to an empty list everywhere here -
without it, _blend's real trend-component would hit live Yahoo Finance and
make these tests both slow and non-deterministic (a real market move on
test-run day could flip an assertion that has nothing to do with the logic
being tested). An empty result is itself a real, handled case (prices.py
returns [] on any failure) - _recent_trend_pct already treats it as "no
trend data", contributing 0 to the blend.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app import predictor as predictor_module
from app.config import settings
from app.models import HistoricalEvent, NewsArticle
from app.predictor import (
    MIN_ARTICLES_PER_TICKER,
    generate_all_predictions,
    group_articles_by_ticker,
)


@pytest.fixture(autouse=True)
def no_live_price_calls(monkeypatch):
    monkeypatch.setattr(predictor_module, "fetch_daily_closes", lambda *a, **k: [])


def _article(title, summary="", sentiment=0.0, categories=None):
    return NewsArticle(
        source="test", title=title, url=f"https://example.com/{title}", summary=summary,
        fetched_at=datetime.now(timezone.utc), sentiment_score=sentiment,
        matched_categories=categories or [],
    )


def test_groups_articles_by_their_detected_ticker():
    articles = [
        _article("Nvidia shares surge on earnings"),
        _article("Nvidia guidance beats expectations"),
        _article("Federal Reserve signals a rate hike"),
    ]
    groups = group_articles_by_ticker(articles)

    assert len(groups["NVDA"]) == 2
    assert len(groups[settings.primary_symbol]) == 1


def test_primary_symbol_always_gets_a_prediction_even_with_no_articles(db):
    results = generate_all_predictions(db)

    assert settings.primary_symbol in results
    assert results[settings.primary_symbol].direction in ("LONG", "SHORT", "NO_TRADE")


def test_a_ticker_below_the_minimum_article_count_is_excluded(db):
    assert MIN_ARTICLES_PER_TICKER >= 2
    db.add(_article("Nvidia shares surge on earnings", sentiment=0.9))  # only 1 article
    db.commit()

    results = generate_all_predictions(db)

    assert "NVDA" not in results


def test_a_ticker_with_enough_articles_gets_its_own_prediction(db):
    db.add_all([
        _article("Tesla unveils new model", sentiment=0.6),
        _article("Tesla deliveries beat estimates", sentiment=0.5),
        _article("Tesla stock rallies on news", sentiment=0.7),
    ])
    db.commit()

    results = generate_all_predictions(db)

    assert "TSLA" in results
    assert results["TSLA"].article_count == 3
    assert results["TSLA"].direction == "LONG"


def test_same_ticker_historical_analogue_is_weighted_more_than_a_different_company(db):
    """A historical event about the SAME ticker should count double in the
    analogue average, per predictor.py's _blend - a direct analogue (e.g. a
    past Tesla reveal) is stronger evidence for a new Tesla headline than an
    unrelated company's product launch in the same category."""
    db.add(HistoricalEvent(
        event_date=datetime(2026, 10, 15, tzinfo=timezone.utc), title="Tesla past reveal",
        category="product_launch", description="d", symbol="TSLA",
        market_move_1d_pct=10.0, market_move_5d_pct=None, source_note="n",
    ))
    db.add(HistoricalEvent(
        event_date=datetime(2019, 11, 22, tzinfo=timezone.utc), title="Unrelated reveal",
        category="product_launch", description="d", symbol="NVDA",
        market_move_1d_pct=-10.0, market_move_5d_pct=None, source_note="n",
    ))
    db.add_all([
        _article("Tesla unveils new product", sentiment=0.0, categories=["product_launch"]),
        _article("Tesla launches another announcement", sentiment=0.0, categories=["product_launch"]),
    ])
    db.commit()

    results = generate_all_predictions(db)

    # Weighted average: [10, 10, -10] / 3 / 10 = +0.0333... (TSLA's own
    # event counted twice) rather than an even [10, -10] / 2 / 10 = 0.0 if
    # both analogues were treated identically - confirms the same-ticker
    # boost actually changed the number, not just that it ran without
    # crashing. Sentiment is 0 here specifically so this component is the
    # only thing that can push the result away from zero.
    assert results["TSLA"].analogue_component > 0
