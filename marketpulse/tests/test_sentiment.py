from __future__ import annotations

from app.sentiment import score_text


def test_clearly_negative_financial_headline_scores_negative():
    result = score_text("Stocks crash as recession fears grip Wall Street")
    assert result.score < -0.3
    assert "crash" in result.matched_words
    assert "recession" in result.matched_words


def test_clearly_positive_financial_headline_scores_positive():
    result = score_text("Nasdaq rallies to a record high on strong earnings beat")
    assert result.score > 0.3
    assert "rally" in result.matched_words or "record high" in result.matched_words


def test_neutral_headline_scores_near_zero():
    result = score_text("Company schedules annual shareholder meeting for next month")
    assert -0.2 < result.score < 0.2


def test_score_is_clamped_to_valid_range():
    text = "crash plunge bankruptcy default bank run contagion " * 5
    result = score_text(text)
    assert -1.0 <= result.score <= 1.0


def test_monetary_policy_keywords_are_tagged():
    result = score_text("Federal Reserve signals another rate hike at next FOMC meeting")
    assert "monetary_policy" in result.categories


def test_geopolitical_keywords_are_tagged():
    result = score_text("Troops launch invasion as war fears escalate sanctions talk")
    assert "geopolitical_conflict" in result.categories


def test_article_can_match_multiple_categories():
    result = score_text("Fed rate hike fears compound war-driven sanctions on energy markets")
    assert "monetary_policy" in result.categories
    assert "geopolitical_conflict" in result.categories


def test_unrelated_text_matches_no_category():
    result = score_text("Local bakery wins award for best croissant in town")
    assert result.categories == []
