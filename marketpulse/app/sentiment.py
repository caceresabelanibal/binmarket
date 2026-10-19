"""Explainable, free, keyless sentiment scoring + event-category tagging.

Deliberately NOT an LLM call: this v1 ships without requiring any paid API
key, so it works the moment it's deployed. VADER (a well-established
lexicon-based sentiment tool, free and pure-Python, no model download) gives
a generic sentiment baseline; a small finance-specific word list then
nudges that score for terms VADER's general-purpose lexicon under- or
mis-weights for market news ("crash", "downgrade", "beats estimates", ...).

This is an explicit, intentional trade-off: a real LLM (Claude/GPT) reading
the same headlines with market context would almost certainly reason better
than a lexicon. The architecture here (one function, one score in, one
score out, every contributing word listed) is built so swapping in a real
LLM call later - once an API key is available - is a localized change to
this one module, not a rewrite. Every score this module produces is
auditable: `scored.matched_words` lists exactly which words moved the
number, so nothing here is a black box.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

_analyzer = SentimentIntensityAnalyzer()


def _contains_phrase(lowered_text: str, phrase: str) -> bool:
    """Word-boundary match, not a bare substring check - "war" must not
    fire on "award", "fed" must not fire on "confederate", etc. A real bug
    this exact test caught before it ever reached production."""
    return re.search(r"\b" + re.escape(phrase.strip()) + r"\b", lowered_text) is not None

# Hand-picked, deliberately short: words with a strong, fairly unambiguous
# polarity in a MARKET-NEWS context specifically (as opposed to general
# text, which is what VADER's own lexicon was built for). Weight is added
# directly to VADER's compound score (-1..+1 range) and the result is
# clamped back into that range.
_FINANCE_LEXICON: dict[str, float] = {
    # negative
    "crash": -0.5, "plunge": -0.4, "plunges": -0.4, "selloff": -0.35, "sell-off": -0.35,
    "recession": -0.4, "default": -0.35, "bankruptcy": -0.45, "bankrupt": -0.4,
    "downgrade": -0.3, "downgraded": -0.3, "layoffs": -0.25, "misses estimates": -0.3,
    "guidance cut": -0.35, "cuts guidance": -0.35, "bank run": -0.45, "contagion": -0.35,
    "sanctions": -0.25, "invasion": -0.3, "war": -0.25, "default risk": -0.3,
    "inflation surges": -0.3, "rate hike": -0.15, "hikes rates": -0.15,
    # positive
    "rally": 0.35, "rallies": 0.35, "surge": 0.35, "surges": 0.35, "record high": 0.4,
    "all-time high": 0.4, "beats estimates": 0.35, "beat estimates": 0.35, "upgrade": 0.3,
    "upgraded": 0.3, "breakthrough": 0.3, "rate cut": 0.2, "cuts rates": 0.2,
    "stimulus": 0.2, "ceasefire": 0.3, "deal reached": 0.25, "soft landing": 0.3,
}

# Category -> trigger keywords, used both to tag incoming articles and to
# look up comparable HistoricalEvent rows. Order doesn't matter; an article
# can match more than one category.
EVENT_CATEGORIES: dict[str, list[str]] = {
    "geopolitical_conflict": ["invasion", "war", "missile", "airstrike", "troops", "ceasefire", "sanctions", "attack"],
    "monetary_policy": ["federal reserve", "fed", "rate hike", "rate cut", "interest rate", "powell", "fomc", "central bank"],
    "earnings": ["earnings", "quarterly results", "beats estimates", "misses estimates", "guidance", "q1 results", "q2 results", "q3 results", "q4 results"],
    "product_launch": ["unveils", "reveals", "launches", "announces new", "keynote", "ai day", "product event"],
    "banking_stress": ["bank collapse", "bank run", "deposits", "bailout", "credit suisse", "regional bank", "svb"],
    "pandemic": ["pandemic", "lockdown", "covid", "outbreak", "quarantine"],
    "trade_policy": ["tariff", "tariffs", "trade war", "export ban", "trade deal"],
}


@dataclass
class ScoredArticle:
    score: float  # -1..+1
    matched_words: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)


def score_text(text: str) -> ScoredArticle:
    lowered = text.lower()
    base = _analyzer.polarity_scores(text)["compound"]

    boost = 0.0
    matched: list[str] = []
    for phrase, weight in _FINANCE_LEXICON.items():
        if _contains_phrase(lowered, phrase):
            boost += weight
            matched.append(phrase)

    score = max(-1.0, min(1.0, base + boost))

    categories = [
        cat for cat, keywords in EVENT_CATEGORIES.items()
        if any(_contains_phrase(lowered, kw) for kw in keywords)
    ]

    return ScoredArticle(score=score, matched_words=matched, categories=categories)
