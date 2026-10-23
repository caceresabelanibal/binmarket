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
    # --- Added to broaden analogue coverage (user-requested: too few events
    # were available as reference) - every number below was independently
    # computed the same way as the rows above, from real Yahoo Finance daily
    # closes fetched directly (not copied from secondary media), following
    # the same "5d = close 5 trading sessions after the 1-day reaction date"
    # convention used throughout this file.
    {
        "event_date": datetime(2024, 4, 15, tzinfo=timezone.utc),
        "title": "Iran launches direct missile/drone attack on Israel",
        "category": "geopolitical_conflict",
        "description": (
            "Iran fired over 300 drones and missiles at Israel overnight Sat Apr 13 2024, the "
            "first direct Iranian attack on Israeli territory - markets were closed over the "
            "weekend; Monday Apr 15 was the first trading reaction. Almost all projectiles were "
            "intercepted and the attack did not escalate into a wider war, so the market reaction "
            "was mild, similar in shape to the Hamas Oct 2023 entry below."
        ),
        "symbol": "^GSPC",
        "market_move_1d_pct": -1.20,
        "market_move_5d_pct": -2.20,
        "source_note": (
            "Computed from real Yahoo Finance daily closes, ^GSPC: 2024-04-12 close 5123.41 -> "
            "2024-04-15 close 5061.82 (-1.20%) -> 2024-04-22 close 5010.60 (-2.20% vs. the 04-12 "
            "base, 5 trading sessions after the 04-15 reaction). Note this window also overlapped "
            "with unrelated hot-inflation-data jitters that week, so not all of the 5-day drift is "
            "attributable to the attack alone."
        ),
    },
    {
        "event_date": datetime(2024, 9, 18, tzinfo=timezone.utc),
        "title": "Fed cuts rates 50bp - first cut since 2020",
        "category": "monetary_policy",
        "description": (
            "FOMC cut rates by 50bp (not the more commonly expected 25bp), the first cut of the "
            "cycle. The index was flat-to-slightly-down into the Sept 18 close as traders digested "
            "the larger-than-usual cut, then rallied sharply the next session as Powell's "
            "press-conference tone was read as confident, not alarmed - another example (like the "
            "June 2022 hike below) of the market pricing in tone over the headline number with a "
            "one-session lag."
        ),
        "symbol": "^GSPC",
        "market_move_1d_pct": -0.29,
        "market_move_5d_pct": 1.56,
        "source_note": (
            "Computed from real Yahoo Finance daily closes, ^GSPC: 2024-09-17 close 5634.58 -> "
            "2024-09-18 close 5618.26 (-0.29%, decision-day close) -> 2024-09-25 close 5722.26 "
            "(+1.56% vs. the 09-17 base, 5 trading sessions after the 09-18 decision). The real "
            "rally mostly happened the very next session (2024-09-19 close 5713.64, +1.70% vs. "
            "09-18) - included here for completeness rather than cherry-picking only the muted "
            "decision-day number."
        ),
    },
    {
        "event_date": datetime(2018, 12, 19, tzinfo=timezone.utc),
        "title": "Fed hikes rates into a slowing market (Dec 2018) - 'Christmas Eve crash'",
        "category": "monetary_policy",
        "description": (
            "FOMC hiked rates a 4th time in 2018 and signaled more hikes ahead, reading as too "
            "hawkish for a market already worried about slowing growth and trade tensions. Stocks "
            "sold off hard into year-end, bottoming on a historically bad Christmas Eve session "
            "before a sharp snapback. A useful counter-example to the June 2022 and Sept 2024 "
            "entries above: the same kind of event (a Fed rate decision) can go either way "
            "depending on what the market already expects and fears."
        ),
        "symbol": "^GSPC",
        "market_move_1d_pct": -1.54,
        "market_move_5d_pct": -2.25,
        "source_note": (
            "Computed from real Yahoo Finance daily closes, ^GSPC: 2018-12-18 close 2546.16 -> "
            "2018-12-19 close 2506.96 (-1.54%) -> 2018-12-27 close 2488.83 (-2.25% vs. the 12-18 "
            "base, 5 trading sessions after the 12-19 decision - a window that includes the "
            "2018-12-24 Christmas Eve session, which alone closed at 2351.10, -7.65% vs. the 12-18 "
            "base, before the index partly recovered into 12-27)."
        ),
    },
    {
        "event_date": datetime(2025, 4, 3, tzinfo=timezone.utc),
        "title": "'Liberation Day' reciprocal tariffs announced",
        "category": "trade_policy",
        "description": (
            "Trump announced sweeping 'reciprocal' tariffs on most US trading partners after the "
            "close Wed Apr 2 2025; China announced retaliatory tariffs over the following weekend. "
            "Triggered one of the worst multi-day selloffs since the 2020 COVID crash and the "
            "first real analogue in this table for trade-policy-driven moves (previously an empty "
            "category here)."
        ),
        "symbol": "^GSPC",
        "market_move_1d_pct": -4.84,
        "market_move_5d_pct": -7.11,
        "source_note": (
            "Computed from real Yahoo Finance daily closes, ^GSPC: 2025-04-02 close 5670.97 -> "
            "2025-04-03 close 5396.52 (-4.84%) -> 2025-04-10 close 5268.05 (-7.11% vs. the 04-02 "
            "base, 5 trading sessions after the 04-03 reaction). That 5-day window already includes "
            "the huge single-day rally from the tariff-pause entry below (2025-04-09, +9.52%), yet "
            "the net 5-day move is still sharply negative - shows how deep the initial selloff was."
        ),
    },
    {
        "event_date": datetime(2025, 4, 9, tzinfo=timezone.utc),
        "title": "Trump pauses most 'Liberation Day' tariffs for 90 days",
        "category": "trade_policy",
        "description": (
            "One week after the tariff announcement above, Trump announced a 90-day pause on most "
            "of the new tariffs (China excluded) while markets were open. Triggered the S&P 500's "
            "best single day since 2008. Paired with the entry above as a real before/after example "
            "of a trade-policy shock followed by a trade-policy relief rally - same category, "
            "opposite direction, both from the same real two-week window."
        ),
        "symbol": "^GSPC",
        "market_move_1d_pct": 9.52,
        "market_move_5d_pct": 5.88,
        "source_note": (
            "Computed from real Yahoo Finance daily closes, ^GSPC: 2025-04-08 close 4982.77 -> "
            "2025-04-09 close 5456.90 (+9.52%) -> 2025-04-16 close 5275.70 (+5.88% vs. the 04-08 "
            "base, 5 trading sessions after the 04-09 reaction - some of the rally gave back in the "
            "days after, consistent with how sharp relief rallies often partly fade)."
        ),
    },
    {
        "event_date": datetime(2025, 1, 27, tzinfo=timezone.utc),
        "title": "DeepSeek shock - Chinese low-cost AI model spooks the AI trade",
        "category": "product_launch",
        "description": (
            "Chinese startup DeepSeek released an AI model (R1) claimed to match leading US models "
            "at a fraction of the training cost, raising doubts about the enormous AI-infrastructure "
            "capex US tech was committing to. NVDA had its largest single-day market-cap loss on "
            "record; the broader NASDAQ fell in sympathy. A real, severe counter-example to the "
            "Tesla Roadster entry below's 'reveal underwhelms, stock dips modestly' pattern - here, "
            "someone ELSE'S product reveal is what moved the stock, and it moved it far harder."
        ),
        "symbol": "NVDA",
        "market_move_1d_pct": -16.97,  # NVDA itself
        "market_move_5d_pct": -18.21,  # NVDA itself
        "source_note": (
            "Computed from real Yahoo Finance daily closes, NVDA: 2025-01-24 close 142.62 -> "
            "2025-01-27 close 118.42 (-16.97%) -> 2025-02-03 close 116.66 (-18.21% vs. the 01-24 "
            "base, 5 trading sessions after the 01-27 reaction). This row's % moves are NVDA's own; "
            "the NASDAQ Composite (^IXIC) moved -3.07% that same day (2025-01-24 close 19954.30 -> "
            "2025-01-27 close 19341.83), independently computed from the same data - a real, "
            "material broad-market spillover from a single company's news, not just noise."
        ),
    },
    {
        "event_date": datetime(2023, 5, 1, tzinfo=timezone.utc),
        "title": "First Republic Bank seized and sold to JPMorgan",
        "category": "banking_stress",
        "description": (
            "Regulators seized First Republic Bank - the second-largest bank failure in US history "
            "at the time - and sold it to JPMorgan in an FDIC-assisted deal announced before the "
            "Monday open. A second, later wave of the same regional-banking stress as the SVB entry "
            "above, but this time the market reaction was muted: the failure was widely expected "
            "and the resolution (an orderly sale, not a bailout) was read as reassuring."
        ),
        "symbol": "^GSPC",
        "market_move_1d_pct": -0.04,
        "market_move_5d_pct": -0.75,
        "source_note": (
            "Computed from real Yahoo Finance daily closes, ^GSPC: 2023-04-28 close 4169.48 -> "
            "2023-05-01 close 4167.87 (-0.04%) -> 2023-05-08 close 4138.12 (-0.75% vs. the 04-28 "
            "base, 5 trading sessions after the 05-01 reaction). A real counter-example to the SVB "
            "entry's sharper reaction: the exact same category of event can land near-flat when "
            "it's already priced in and resolved in an orderly way."
        ),
    },
    {
        "event_date": datetime(2020, 11, 9, tzinfo=timezone.utc),
        "title": "Pfizer/BioNTech announce 90%+ effective COVID vaccine",
        "category": "pandemic",
        "description": (
            "Pfizer and BioNTech announced their vaccine candidate was over 90% effective in Phase "
            "3 trials, the first major positive vaccine readout of the pandemic. A real, positive "
            "counter-example to the COVID-crash entry above - this table's only other 'pandemic' "
            "row is an extreme crash day, which would otherwise bias any pandemic-category analogue "
            "match entirely negative regardless of what the actual news is."
        ),
        "symbol": "^GSPC",
        "market_move_1d_pct": 1.17,
        "market_move_5d_pct": 3.35,
        "source_note": (
            "Computed from real Yahoo Finance daily closes, ^GSPC: 2020-11-06 close 3509.44 -> "
            "2020-11-09 close 3550.50 (+1.17%) -> 2020-11-16 close 3626.91 (+3.35% vs. the 11-06 "
            "base, 5 trading sessions after the 11-09 reaction)."
        ),
    },
    {
        "event_date": datetime(2024, 10, 24, tzinfo=timezone.utc),
        "title": "Tesla Q3 2024 earnings beat - best single day in years",
        "category": "earnings",
        "description": (
            "Tesla reported Q3 2024 results after the close Oct 23 2024, beating on margins and "
            "giving confident delivery-growth guidance for 2025; the stock had its best single day "
            "since 2013 the next session. Same ticker as the Roadster Rocket product-launch entry "
            "below - gives TSLA-specific news a genuine same-ticker earnings analogue, not just a "
            "same-ticker product-launch one."
        ),
        "symbol": "TSLA",
        "market_move_1d_pct": 21.92,  # TSLA itself
        "market_move_5d_pct": 16.94,  # TSLA itself
        "source_note": (
            "Computed from real Yahoo Finance daily closes, TSLA: 2024-10-23 close 213.65 -> "
            "2024-10-24 close 260.48 (+21.92%) -> 2024-10-31 close 249.85 (+16.94% vs. the 10-23 "
            "base, 5 trading sessions after the 10-24 reaction - some of the single-day pop faded "
            "over the following week, which is common after an outsized earnings-reaction day)."
        ),
    },
]


def seed_historical_events(db) -> int:
    """Additive and idempotent: inserts any SEED_EVENTS row whose title isn't
    already present, and touches nothing else - safe to run on every
    startup, and lets this curated list keep growing across deploys (as it
    did the first time it grew, from 9 to 18 rows) without needing a
    one-off migration or wiping hand-verified data already in the table.
    Returns how many rows were newly inserted."""
    existing_titles = {title for (title,) in db.query(HistoricalEvent.title).all()}
    inserted = 0
    for row in SEED_EVENTS:
        if row["title"] in existing_titles:
            continue
        db.add(HistoricalEvent(**row))
        inserted += 1
    if inserted:
        db.commit()
    return inserted
