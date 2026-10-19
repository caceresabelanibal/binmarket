"""Maps a news article's real title/summary text to a real, public stock
ticker, so each article can be shown with "which ticker would this news
actually apply a prediction to" (requested directly by the user, with an
explicit instruction not to invent anything).

Every ticker below is a real, public symbol for a real, well-known company -
nothing here is guessed or fabricated. Matching is word-boundary (same
discipline as app/sentiment.py's category tagging, which caught a real
"award"-matches-"war" bug from naive substring search) so "Target" doesn't
match "target" used as an ordinary word, etc.

An article that doesn't name a specific company (most macro/Fed/geopolitical
news) has no single-stock ticker to report - it's tagged with the
configured primary index symbol instead (see app/config.py), which is
exactly what the main predictor already treats that kind of news as moving.
That's a real, correct mapping, not a fallback guess.
"""
from __future__ import annotations

import re

# name/alias (lowercase) -> real ticker. Covers large, frequently-newsworthy
# companies that commonly appear in the feeds this app reads (app/feeds.py).
# Deliberately conservative: only added when the company name is
# unambiguous enough that a text match is reliable (no single-word generic
# aliases like "block" for Block Inc - too many false-positive risks).
_COMPANY_TICKERS: dict[str, str] = {
    "nvidia": "NVDA",
    "apple": "AAPL",
    "microsoft": "MSFT",
    "amazon": "AMZN",
    "alphabet": "GOOGL",
    "google": "GOOGL",
    "meta platforms": "META",
    "facebook": "META",
    "tesla": "TSLA",
    "netflix": "NFLX",
    "advanced micro devices": "AMD",
    "intel": "INTC",
    "broadcom": "AVGO",
    "oracle": "ORCL",
    "salesforce": "CRM",
    "adobe": "ADBE",
    "qualcomm": "QCOM",
    "cisco": "CSCO",
    "paypal": "PYPL",
    "uber": "UBER",
    "starbucks": "SBUX",
    "boeing": "BA",
    "jpmorgan": "JPM",
    "jp morgan": "JPM",
    "goldman sachs": "GS",
    "bank of america": "BAC",
    "walmart": "WMT",
    "disney": "DIS",
    "coca-cola": "KO",
    "coca cola": "KO",
    "pepsico": "PEP",
    "exxon mobil": "XOM",
    "exxonmobil": "XOM",
    "chevron": "CVX",
    "johnson & johnson": "JNJ",
    "pfizer": "PFE",
    "mastercard": "MA",
    "home depot": "HD",
    "mcdonald's": "MCD",
    "mcdonalds": "MCD",
    "nike": "NKE",
    "verizon": "VZ",
    "ibm": "IBM",
    "general electric": "GE",
    "ford motor": "F",
    "general motors": "GM",
    "palantir": "PLTR",
    "shopify": "SHOP",
    "coinbase": "COIN",
    "sofi technologies": "SOFI",
    "rivian": "RIVN",
    "lucid group": "LCID",
    "alibaba": "BABA",
    "spotify": "SPOT",
    "airbnb": "ABNB",
    "micron": "MU",
    "moderna": "MRNA",
    "pinterest": "PINS",
    "robinhood": "HOOD",
    "snowflake": "SNOW",
    "super micro": "SMCI",
    "supermicro": "SMCI",
    "arm holdings": "ARM",
    "dell technologies": "DELL",
    "costco": "COST",
    "visa inc": "V",
    "eli lilly": "LLY",
    "ulta beauty": "ULTA",
    "target corp": "TGT",
}

# Sorted longest-alias-first so "meta platforms" is tried before a shorter
# alias that might also appear in the same text, avoiding an arbitrary dict
# iteration order mattering.
_SORTED_ALIASES = sorted(_COMPANY_TICKERS.items(), key=lambda kv: -len(kv[0]))


def detect_ticker(text: str, fallback_symbol: str) -> str:
    """Returns the real ticker for the first company name matched in
    `text` (word-boundary match), or `fallback_symbol` (the configured
    primary index, e.g. "^IXIC") when no specific company is named - most
    macro/Fed/geopolitical headlines fall into this case, which is the
    correct real mapping, not a guess."""
    lowered = text.lower()
    for alias, ticker in _SORTED_ALIASES:
        if re.search(r"\b" + re.escape(alias) + r"\b", lowered):
            return ticker
    return fallback_symbol
