"""Regression tests for the real production incident: news_articles
reached 2,041 rows within 3 days of deployment with zero retention, which is
exactly what made generate_prediction's old hardcoded query limit start
silently truncating real data (confirmed: 1,421 real articles existed in a
48h window against a .limit(300) query).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.ingest import NEWS_ARTICLE_RETENTION_DAYS, PREDICTION_RETENTION_DAYS, prune_old_data
from app.models import NewsArticle, Prediction


def _article(fetched_at, url):
    return NewsArticle(
        source="test", title="t", url=url, summary="s", fetched_at=fetched_at,
        sentiment_score=0.0, matched_categories=[],
    )


def _prediction(created_at, symbol="^IXIC"):
    return Prediction(
        symbol=symbol, created_at=created_at, horizon_hours=48, direction="NO_TRADE",
        confidence_pct=0.0, sentiment_score=0.0, reasoning={},
    )


def test_prunes_articles_older_than_retention(db):
    now = datetime.now(timezone.utc)
    old = _article(now - timedelta(days=NEWS_ARTICLE_RETENTION_DAYS + 1), "https://example.com/old")
    recent = _article(now - timedelta(days=1), "https://example.com/recent")
    db.add_all([old, recent])
    db.commit()

    pruned_articles, _ = prune_old_data(db)

    assert pruned_articles == 1
    remaining = db.query(NewsArticle).all()
    assert [r.url for r in remaining] == ["https://example.com/recent"]


def test_prunes_predictions_older_than_retention(db):
    now = datetime.now(timezone.utc)
    old = _prediction(now - timedelta(days=PREDICTION_RETENTION_DAYS + 1))
    recent = _prediction(now - timedelta(days=1))
    db.add_all([old, recent])
    db.commit()

    _, pruned_predictions = prune_old_data(db)

    assert pruned_predictions == 1
    assert db.query(Prediction).count() == 1


def test_keeps_recent_data_untouched(db):
    now = datetime.now(timezone.utc)
    db.add(_article(now, "https://example.com/fresh"))
    db.add(_prediction(now))
    db.commit()

    pruned_articles, pruned_predictions = prune_old_data(db)

    assert pruned_articles == 0
    assert pruned_predictions == 0
