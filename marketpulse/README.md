# MarketPulse

A standalone market-analysis service: reads free, open news/finance RSS
feeds, scores sentiment, matches current news against a curated table of
real historical events, and turns that into an explainable directional
outlook (LONG / SHORT / NO_TRADE) for a configured symbol over the next N
hours - exposed as a plain JSON API another system (e.g. BinMarket) can
poll.

**This is a separate application from BinMarket.** Same git repository and
the same production server, nothing else: its own Docker image, its own
Postgres, its own ports, its own auth, zero imports from BinMarket's code.
It is meant to be fully portable - built once, then `docker save`/`push`ed
and run on a different machine with nothing but this `marketpulse/`
directory and a `.env` file.

## Why direction, not magnitude

Predicting a market's exact move is far harder (and far less reliably
useful) than predicting its *direction* over a short window. Every design
choice here follows that: the scoring is a sign (-1..+1), the output is a
sign (LONG/SHORT/NO_TRADE), and the backtest (`/api/v1/backtest`, and the
dashboard's Backtest card) scores whether the *direction* called out
matched what actually happened - never whether the magnitude was close.

## Architecture

- **`marketpulse-db`** - Postgres, isolated volume (`marketpulse_db_data`),
  not shared with BinMarket's database in any way.
- **`marketpulse-app`** - a single FastAPI container that does three jobs at
  once (deliberately one container, not three, for easy portability):
  1. Serves the JSON API (`/api/v1/...`) and a small server-rendered
     dashboard (`/`, `/login`) with cookie-based auth.
  2. Runs a background `asyncio` loop (see `app/scheduler.py`) every
     `MARKETPULSE_INGEST_INTERVAL_MINUTES` (default 30) that: fetches every
     configured feed, scores new articles, refreshes a small daily-close
     price cache for the tracked symbol, and stores a fresh prediction
     snapshot.
  3. Seeds its own schema and a curated historical-events table on first
     startup (`app/seed.py`, `app/events_seed.py`) - idempotent, safe on
     every restart.

## The prediction engine (`app/predictor.py`)

A transparent weighted blend, **not an LLM call and not a black box**:

```
combined = news_sentiment * 0.55 + historical_analogue_prior * 0.25 + recent_trend * 0.20
```

- **News sentiment**: VADER (a free, lexicon-based sentiment tool) plus a
  small finance-specific word list (`app/sentiment.py`) that nudges scores
  for terms VADER's general-purpose lexicon under/mis-weights for market
  news ("crash", "downgrade", "beats estimates", ...). Recency-weighted -
  an hour-old headline counts far more than a 47-hour-old one.
- **Historical analogue prior**: incoming articles are tagged into
  categories (`geopolitical_conflict`, `monetary_policy`, `earnings`,
  `product_launch`, `banking_stress`, `pandemic`, `trade_policy`) by keyword
  match. When a category has at least 2 matching articles right now, its
  real historical reaction (from `app/events_seed.py` - see below) is
  blended in as a prior.
  - False-positive risk at this scale is a real risk, not a hypothetical
    one - there's a test (`tests/test_sentiment.py`) that caught naive
    substring matching flagging "award" as containing "war" before this
    ever shipped. Every keyword match uses word-boundary regex, not a bare
    substring check.
- **Recent trend**: the tracked symbol's real 5-day price move (from Yahoo
  Finance / FRED, both free and keyless - see `app/prices.py`), as a light
  confirmation signal, not a driver on its own.

Every number that goes into a prediction is stored in `Prediction.reasoning`
(a JSON column) and surfaced on the dashboard and in the API response -
every contributing article, every matched historical event, every
component's weight. Nothing is hidden inside a model's weights.

### This v1 deliberately ships without an LLM

A real LLM (Claude/GPT) reading the same headlines with market context
would almost certainly reason better than a lexicon-plus-keyword-matching
approach. This v1 ships without requiring any paid API key so it works
immediately on deployment; the architecture (one function, `score_text`, in
`app/sentiment.py`) is built so swapping in a real LLM call later is a
localized change to that one module, not a rewrite. If an Anthropic/OpenAI
API key becomes available, that's the natural next upgrade.

## Historical events (`app/events_seed.py`)

Nine real, dated events across six categories (wars/geopolitical shocks,
Fed policy shocks, a banking-stress shock, the COVID crash, and three
single-company shocks - a 2026 Tesla "flying Roadster" reveal, an Nvidia
earnings beat, and Meta's 2022 earnings-miss crash). **Every
`market_move_*_pct` figure was independently computed from real Yahoo
Finance daily closing prices** (not copied from secondary media reports,
which were cross-checked during research and often gave inconsistent
numbers for the same event) - each row's `source_note` names the exact two
closing prices the percentage is between, so any number can be re-verified
independently. Single-stock events are flagged as weaker analogues for a
broad-index call than the index-level ones.

### Does this table grow on its own?

Two different things happen here, and they're worth keeping separate:

- **News (`news_articles`) grows continuously** - every ingest cycle adds
  whatever's genuinely new from the 9 feeds.
- **Historical events (`historical_events`) is hand-curated and does NOT
  auto-add brand-new events.** Deciding "this is a real, comparable
  analogue" needs human judgment - auto-adding events from news volume/
  sentiment spikes would risk polluting a small, verified table with noise.
  Adding a new event is a deliberate edit to `events_seed.py`.
  What DOES happen automatically: `app/events_backfill.py` fills in a
  `market_move_5d_pct` that didn't exist yet at seed time (an event added
  less than 5 real trading days ago) with the real number, once enough
  trading days have genuinely passed - never estimated, never guessed.
  This is why the Tesla Roadster entry below may show `None` for its 5-day
  move for a few days after you read this.

## Feeds (`app/feeds.py`)

Nine free, keyless sources, each verified reachable by actually fetching it
(not just commonly cited) before being listed: CNBC (top news + business),
MarketWatch, Investing.com, the Federal Reserve (all releases + monetary
policy specifically), the SEC, and Yahoo Finance's legacy per-symbol
headline RSS for the Nasdaq Composite and S&P 500. Reddit's public JSON
endpoints were tested and excluded - they return a 403 "blocked due to
network policy" from this server's IP (a datacenter-IP anti-bot block, not
a dead endpoint; would need a residential IP or real API auth). Reuters'
public RSS was confirmed discontinued. See the module docstring for exact
URLs and the reasoning behind every exclusion.

## Running it

```bash
cd marketpulse
cp .env.example .env   # fill in real values - especially the three secrets
docker compose up -d --build
```

Dashboard: `http://<host>:8300/` (port configurable via
`MARKETPULSE_HOST_PORT` in `.env`). Login with `MARKETPULSE_ADMIN_USERNAME`
/ `MARKETPULSE_ADMIN_PASSWORD` from your `.env`.

The bot-facing API needs no auth: `GET /api/v1/outlook` (add `?fresh=true`
to force a brand-new computation instead of the last scheduled one).

## Moving this to another machine

This whole directory is self-contained - nothing outside it is referenced.
Two ways to get the built image onto another machine:

**Option A - save/load (no registry needed):**
```bash
docker save marketpulse-app:latest | gzip > marketpulse-app.tar.gz
# copy the file to the other machine (scp, USB, etc.), then:
docker load < marketpulse-app.tar.gz
```

**Option B - push to a registry you control** (Docker Hub, GHCR, etc.):
```bash
docker tag marketpulse-app:latest <your-registry>/marketpulse-app:latest
docker push <your-registry>/marketpulse-app:latest
# on the other machine:
docker pull <your-registry>/marketpulse-app:latest
```

Either way, bring this `marketpulse/` directory (for `docker-compose.yml`
and a `.env`) along too - the compose file still builds `marketpulse-app`
from source by default; point `image:` at the pulled tag (or run
`docker compose up -d` without `--build` once the image is loaded/pulled
locally under the same tag) to use the prebuilt image instead of rebuilding.

## Honesty, limits, and what to watch

- **This predicts a hard, genuinely speculative thing.** Academic research
  on news-sentiment-driven market direction prediction consistently finds
  weak edge. Treat every outlook as a hypothesis to check against the
  Backtest card, not a fact.
- **No predictions exist before this was deployed** - the backtest's hit
  rate will be thin at first and grow more meaningful over days/weeks as
  real predictions accumulate real verdicts (a prediction only gets scored
  once its horizon has actually elapsed - see `app/backtest.py`).
- **Single-stock historical analogues (Tesla, Nvidia, Meta) are weaker
  evidence for a broad-index call** than the index-level events - they're
  included because the user specifically asked for product-launch-style
  case studies, but the predictor should not be expected to lean on them
  for the primary NASDAQ/S&P outlook.
