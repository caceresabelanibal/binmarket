"""Free, keyless news feeds - verified reachable by actually fetching them
(not just commonly-cited) before being listed here. See the research notes
in this repo's commit history for exactly how each was checked.

Explicitly excluded, with reasons (don't re-add without re-verifying):
- Reddit (`/r/stocks/.json`, `/r/wallstreetbets/.json`): returns 403 from
  this server's IP ("blocked due to a network policy") - a datacenter-IP
  block, not a dead endpoint. Would need a residential IP or real Reddit API
  auth to use; left out of v1 rather than silently failing forever.
- Reuters RSS: discontinued publicly years ago (confirmed 401/404 on every
  known path).
- The generic `finance.yahoo.com/news/rssindex` endpoint: dead (served HTML,
  not RSS). The per-symbol legacy endpoint below still works.
"""
from __future__ import annotations

from dataclasses import dataclass

import feedparser
import httpx

# A browser-like UA is required for CNBC and Yahoo (both reject bare
# `python-httpx` user agents with a 403) - harmless for the others.
_UA = "Mozilla/5.0 (compatible; MarketPulseBot/1.0; +https://github.com/)"


@dataclass
class FeedSource:
    name: str
    url: str


FEEDS: list[FeedSource] = [
    FeedSource("CNBC Top News", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    FeedSource("CNBC Business", "https://www.cnbc.com/id/10001147/device/rss/rss.html"),
    FeedSource("MarketWatch Top Stories", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    FeedSource("Investing.com All News", "https://www.investing.com/rss/news.rss"),
    FeedSource("Federal Reserve - All Releases", "https://www.federalreserve.gov/feeds/press_all.xml"),
    FeedSource("Federal Reserve - Monetary Policy", "https://www.federalreserve.gov/feeds/press_monetary.xml"),
    FeedSource("SEC Press Releases", "https://www.sec.gov/news/pressreleases.rss"),
    FeedSource("Yahoo Finance - NASDAQ Composite", "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%5EIXIC&region=US&lang=en-US"),
    FeedSource("Yahoo Finance - S&P 500", "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%5EGSPC&region=US&lang=en-US"),
]


@dataclass
class FetchedItem:
    title: str
    url: str
    summary: str
    published_at: str | None  # ISO string or None if the feed didn't say


def fetch_feed(source: FeedSource, timeout: float = 10.0) -> list[FetchedItem]:
    """Never raises - a single bad/slow feed must never take down the whole
    ingest cycle. Returns an empty list on any failure."""
    try:
        resp = httpx.get(source.url, headers={"User-Agent": _UA}, timeout=timeout, follow_redirects=True)
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
    except Exception:
        return []

    items: list[FetchedItem] = []
    for entry in parsed.entries:
        link = entry.get("link")
        title = entry.get("title")
        if not link or not title:
            continue
        published = entry.get("published") or entry.get("updated")
        items.append(FetchedItem(
            title=title,
            url=link,
            summary=entry.get("summary", "") or "",
            published_at=published,
        ))
    return items
