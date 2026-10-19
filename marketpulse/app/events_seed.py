"""Curated real historical events, seeded once at startup if the table is
empty. Every `market_move_*_pct` figure here was independently computed by
this project from real Yahoo Finance daily closing prices for ^GSPC
(S&P 500) / ^IXIC (NASDAQ Composite) or the named single stock - NOT taken
from secondary media reports, which (when cross-checked during research for
this file) often gave inconsistent or approximate figures for the same
event. Each `source_note` says exactly which two closes the % move is
between, so any number here can be independently re-verified.

Single-stock events (Tesla, Nvidia, Meta) are idiosyncratic / company-
specific - matching one of their categories is a much weaker analogue for a
broad-index call than the index-level events, and the predictor should
(and does) weight them accordingly.

Each row's `symbol` records which real symbol its numbers came from. An
event seeded less than 5 real trading days ago can have
`market_move_5d_pct=None` because that real number genuinely doesn't exist
yet - see app/events_backfill.py, which fills it in automatically with real
data once enough time has actually passed, never by estimating. That
backfill (not auto-detecting brand-new events, which would risk polluting
a hand-curated table with noise) is how this table "grows" over time.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .models import HistoricalEvent

SEED_EVENTS: list[dict] = [
    {
        "event_date": datetime(2022, 2, 24, tzinfo=timezone.utc),
        "title": "Russia invades Ukraine",
        "category": "geopolitical_conflict",
        "description": (
            "Russian forces invaded Ukraine. US equity futures sold off at the open on war-risk "
            "fears, then markets reversed intraday and closed higher - a pattern CFRA's Sam "
            "Stovall and others have described as typical for geopolitical shocks: sharp, "
            "short-lived."
        ),
        "symbol": "^GSPC",
        "market_move_1d_pct": 1.50,  # S&P 500: computed from real data below
        "market_move_5d_pct": 3.27,
        "source_note": (
            "Computed from real Yahoo Finance daily closes, ^GSPC: 2022-02-23 close 4225.50 -> "
            "2022-02-24 close 4288.70 (+1.50%) -> 2022-03-03 close 4363.49 (+3.27% vs. the 02-23 "
            "base, 5 trading days later). NASDAQ Composite (^IXIC) moved +3.34% that day and "
            "+3.84% over the same 5-day window - a larger reaction than the S&P, consistent with "
            "tech's higher beta."
        ),
    },
    {
        "event_date": datetime(2023, 10, 9, tzinfo=timezone.utc),
        "title": "Hamas attack on Israel - first trading day reaction",
        "category": "geopolitical_conflict",
        "description": (
            "Hamas attacked Israel on Saturday Oct 7, 2023, while US markets were closed; Monday "
            "Oct 9 was the first trading reaction. US futures dipped overnight but the S&P 500 "
            "closed slightly positive; defense stocks and energy outperformed."
        ),
        "symbol": "^GSPC",
        "market_move_1d_pct": 0.63,
        "market_move_5d_pct": 1.51,
        "source_note": (
            "Computed from real Yahoo Finance daily closes, ^GSPC: 2023-10-06 close 4308.50 -> "
            "2023-10-09 close 4335.66 (+0.63%) -> 2023-10-16 close 4373.63 (+1.51% vs. the 10-06 "
            "base). A mild, short-lived reaction - consistent with most geopolitical shocks not "
            "directly threatening major energy supply or involving a nuclear power."
        ),
    },
    {
        "event_date": datetime(2023, 3, 10, tzinfo=timezone.utc),
        "title": "Silicon Valley Bank collapse",
        "category": "banking_stress",
        "description": (
            "Regulators seized Silicon Valley Bank, the largest US bank failure since 2008, "
            "triggering a regional-banking panic that spread through the following week before a "
            "federal depositor backstop calmed markets."
        ),
        "symbol": "^GSPC",
        "market_move_1d_pct": -1.45,
        "market_move_5d_pct": -0.04,
        "source_note": (
            "Computed from real Yahoo Finance daily closes, ^GSPC: 2023-03-09 close 3918.32 -> "
            "2023-03-10 close 3861.59 (-1.45%) -> 2023-03-17 close 3916.64 (-0.04% vs. the 03-09 "
            "base - the index round-tripped back to roughly even within 5 trading days, but with a "
            "sharp drawdown and regional-bank-specific carnage in between; NASDAQ fared better over "
            "the same window at +2.58%, since the panic was concentrated in regional banks, not "
            "large-cap tech)."
        ),
    },
    {
        "event_date": datetime(2020, 3, 16, tzinfo=timezone.utc),
        "title": "COVID-19 crash - worst single day",
        "category": "pandemic",
        "description": (
            "The single worst day of the COVID-19 crash, immediately after the Fed's emergency "
            "weekend rate cut to near-zero failed to calm markets. One of the largest single-day "
            "percentage losses on record for both the S&P 500 and NASDAQ."
        ),
        "symbol": "^GSPC",
        "market_move_1d_pct": -11.98,
        "market_move_5d_pct": -17.47,
        "source_note": (
            "Computed from real Yahoo Finance daily closes, ^GSPC: 2020-03-13 close 2711.02 -> "
            "2020-03-16 close 2386.13 (-11.98%) -> 2020-03-23 close 2237.40 (-17.47% vs. the 03-13 "
            "base; 2020-03-23 was the eventual crash bottom). This is an extreme, low-frequency "
            "tail event - treat any analogue match against it as a strong signal, not routine noise."
        ),
    },
    {
        "event_date": datetime(2022, 6, 15, tzinfo=timezone.utc),
        "title": "Fed hikes rates 75bp (largest since 1994)",
        "category": "monetary_policy",
        "description": (
            "FOMC raised rates 75bp - the largest hike since 1994 - but the move was >90% priced "
            "in; the market rallied on Powell's press-conference tone (signaling 75bp moves "
            "'would not become common'), snapping a 5-session losing streak."
        ),
        "symbol": "^GSPC",
        "market_move_1d_pct": 1.46,
        "market_move_5d_pct": 1.61,
        "source_note": (
            "Computed from real Yahoo Finance daily closes, ^GSPC: 2022-06-14 close 3735.48 -> "
            "2022-06-15 close 3789.99 (+1.46%) -> 2022-06-23 close 3795.73 (+1.61% vs. the 06-14 "
            "base). Illustrates that for monetary-policy events, the market often reacts to the "
            "tone/forward guidance more than the headline number itself."
        ),
    },
    {
        "event_date": datetime(2023, 12, 13, tzinfo=timezone.utc),
        "title": "Fed dovish pivot (Dec 2023 FOMC)",
        "category": "monetary_policy",
        "description": (
            "The Fed held rates and its dot plot signaled roughly three rate cuts in 2024, "
            "triggering what the financial press dubbed a 'Santa rally' into year-end."
        ),
        "symbol": "^GSPC",
        "market_move_1d_pct": 1.37,
        "market_move_5d_pct": 1.18,
        "source_note": (
            "Computed from real Yahoo Finance daily closes, ^GSPC: 2023-12-12 close 4643.70 -> "
            "2023-12-13 close 4707.09 (+1.37%) -> 2023-12-20 close 4698.35 (+1.18% vs. the 12-12 "
            "base). Secondary media reporting on this event's exact single-day move was "
            "inconsistent when checked - these figures are the directly-computed real closes, not "
            "a media citation."
        ),
    },
    {
        # Replaces the earlier Cybertruck (2019) entry at the user's request,
        # pointing at a more recent, more specific "flying car" reveal.
        # event_date is the first TRADING-DAY reaction (Fri 2026-10-16), same
        # convention as the Hamas entry above (attack Sat Oct 7 2023, entry
        # dated Mon Oct 9 2023's reaction) - keeps the backfill logic in
        # app/events_backfill.py simple: always "the day the market actually
        # responded", not the calendar day of the news itself.
        "event_date": datetime(2026, 10, 16, tzinfo=timezone.utc),
        "title": "Tesla reveals a flying Roadster (\"Roadster Rocket\") - stock reaction",
        "category": "product_launch",
        "description": (
            "Tesla revealed an updated Roadster with a cold-gas-thruster 'flying' version (dubbed "
            "the Roadster Rocket) at a Thursday-night (2026-10-15) event, demonstrating it driving "
            "up a ramp, flipping in midair, and landing on its wheels; manufacturing was said to "
            "start in 2028. Coverage described public reaction as disbelief/skepticism (some "
            "assuming CGI or a lightweight mockup). Idiosyncratic, single-stock event - no "
            "broad-market claim is made here."
        ),
        "symbol": "TSLA",
        "market_move_1d_pct": -2.13,
        "market_move_5d_pct": None,
        "source_note": (
            "Computed from real Yahoo Finance daily closes, TSLA: 2026-10-15 close 362.44 -> "
            "2026-10-16 (first trading day after the Thursday-night reveal) close 354.72 (-2.13%). "
            "The 5-trading-day figure is deliberately left unset, not estimated: as of this entry's "
            "creation only 2 trading days had elapsed since the event (2026-10-16 and 2026-10-19), "
            "so a real 5-day close doesn't exist yet. app/events_backfill.py will fill it in "
            "automatically, with real data, once enough trading days have genuinely passed - not "
            "estimated or guessed in the meantime. Note the stock actually FELL on reaction, "
            "despite the stunt - a real, verified counter-example to any assumption that a flashy "
            "product reveal automatically lifts the stock; skepticism/disbelief in the coverage "
            "plausibly explains the muted-to-negative reaction. This is a SINGLE-STOCK move, not an "
            "index move - included as the weakest kind of analogue (company-specific product "
            "reveals rarely move the broad market on their own)."
        ),
    },
    {
        "event_date": datetime(2023, 5, 25, tzinfo=timezone.utc),
        "title": "Nvidia AI guidance beat - stock + NASDAQ spillover",
        "category": "earnings",
        "description": (
            "Nvidia guided next-quarter revenue to ~$11B vs. ~$7.2B consensus, an unprecedented "
            "beat attributed to AI-chip demand. NVDA stock jumped and the broader semiconductor / "
            "mega-cap tech complex rallied in sympathy, lifting the NASDAQ Composite same-day."
        ),
        "symbol": "NVDA",
        "market_move_1d_pct": 24.37,  # NVDA itself
        "market_move_5d_pct": 28.78,  # NVDA itself
        "source_note": (
            "Computed from real Yahoo Finance daily closes, NVDA: 2023-05-24 close 30.54 -> "
            "2023-05-25 close 37.98 (+24.37%) -> 2023-06-02 close 39.33 (+28.78% vs. the 05-24 "
            "base). This row's % moves are NVDA's own - the broader-market spillover is real but "
            "smaller: NASDAQ Composite (^IXIC) moved +1.71% that same day (2023-05-24 close "
            "12484.16 -> 2023-05-25 close 12698.09), independently computed from the same data."
        ),
    },
    {
        "event_date": datetime(2022, 2, 3, tzinfo=timezone.utc),
        "title": "Meta earnings miss - largest single-day market-cap loss (at the time)",
        "category": "earnings",
        "description": (
            "Meta (Facebook) missed EPS estimates, reported its first-ever daily-active-user "
            "decline, and gave weak guidance partly attributed to Apple's iOS privacy changes "
            "hurting ad targeting - erasing roughly $230-250B in market cap in one day, the "
            "largest single-day market-cap loss for any US company at the time."
        ),
        "symbol": "META",
        "market_move_1d_pct": -26.39,  # META itself
        "market_move_5d_pct": -29.39,  # META itself
        "source_note": (
            "Computed from real Yahoo Finance daily closes, META: 2022-02-02 close 323.00 -> "
            "2022-02-03 close 237.76 (-26.39%) -> 2022-02-10 close 228.07 (-29.39% vs. the 02-02 "
            "base). This row's % moves are META's own, a single mega-cap stock, not a broad-index "
            "move - useful as an analogue for 'how hard can a single disappointing mega-cap "
            "earnings report get hit', not for predicting the whole market."
        ),
    },
]


def seed_historical_events(db) -> int:
    """Idempotent: does nothing if the table already has rows (this is seed
    data, not something the app re-syncs). Returns how many rows were
    inserted."""
    existing = db.query(HistoricalEvent).count()
    if existing > 0:
        return 0
    for row in SEED_EVENTS:
        db.add(HistoricalEvent(**row))
    db.commit()
    return len(SEED_EVENTS)
