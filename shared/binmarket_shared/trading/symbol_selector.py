"""Automatic symbol selection (requested directly by the user): instead of
picking pairs by hand in Market, the tool can pick the ones "it senses will
move" on its own.

There is no way to compute our own volatility for the ~1000+ USDT pairs on
Binance without historical candles for all of them, which we don't have. The
pragmatic, honest signal available for every pair right now, with a single
public API call, is Binance's own 24h ticker stats — so "intuye que va a
tener fluctuaciones" is implemented as: rank by how much a pair has actually
moved in the last 24h, after filtering out illiquid pairs (a huge % move on
tiny volume is far more likely to be a manipulated/illiquid coin than a real
opportunity, and would suffer terrible slippage anyway).

This never touches a symbol the user selected by hand (`is_auto_selected`
tracks which rows this module is allowed to manage).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from binmarket_shared.binance.client import BinanceClient
from binmarket_shared.db.models import Position, PositionStatus, Signal, Symbol

logger = logging.getLogger("binmarket.symbol_selector")

# A pair that moved more than this in 24h is almost certainly already in a
# blow-off pump/dump - exactly the kind of move that `classify_regime()`
# will (correctly) flag as EXTREME_VOLATILITY, which every strategy refuses
# to trade. Picking "the single biggest mover on Binance" therefore tends to
# pick the one pair guaranteed to sit idle. Capping the search to strong-but-
# not-extreme moves is what actually gets picked symbols trading.
MAX_PRICE_CHANGE_PCT_24H = 20.0

# How far back to look for a regime reading already computed by the engine
# for a candidate. If its own most recent reading says EXTREME_VOLATILITY,
# reselecting it would just repeat the same do-nothing cycle.
STUCK_REGIME_LOOKBACK_MINUTES = 30

# Once a symbol has had its turn, keep it out of the running for a while so
# the bot actually rotates across different symbols as trends shift, instead
# of indefinitely re-picking whatever single pair happens to still be the
# best mover (a real symbol can legitimately stay "hottest" for hours,
# which otherwise means every trade for a whole session is on one pair -
# not what "va variando, mirando las tendencias" asked for).
ROTATION_COOLDOWN_MINUTES = 60


def _is_stuck_in_extreme_volatility(db: Session, symbol: str) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=STUCK_REGIME_LOOKBACK_MINUTES)
    latest = (
        db.query(Signal.regime)
        .filter(Signal.symbol == symbol, Signal.created_at >= cutoff)
        .order_by(Signal.created_at.desc())
        .first()
    )
    return bool(latest and latest[0].endswith("EXTREME_VOLATILITY"))


def _has_open_position(db: Session, symbol: str) -> bool:
    return db.query(Position).filter(Position.symbol == symbol, Position.status == PositionStatus.OPEN).first() is not None


def _in_rotation_cooldown(db: Session, symbol: str) -> bool:
    # An open position always counts as "in cooldown" - both to keep it out
    # of the running for a *new* pick, and (see select_volatile_symbols)
    # because a symbol with a live position must never be deselected: the
    # engine only ticks symbols with is_selected=True, so deselecting one
    # mid-trade would silently orphan it - no more stop-loss/take-profit
    # checks, forever.
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=ROTATION_COOLDOWN_MINUTES)
    return (
        db.query(Position)
        .filter(Position.symbol == symbol, or_(Position.status == PositionStatus.OPEN, Position.opened_at >= cutoff))
        .first()
        is not None
    )


def select_volatile_symbols(
    db: Session,
    binance_client: BinanceClient,
    max_symbols: int,
    min_volume_usdt: float,
) -> list[str]:
    """Ranks liquid USDT pairs by |24h price change %| (excluding blow-off
    moves that are already too extreme to trade, and pairs the engine has
    just classified as EXTREME_VOLATILITY) and marks the top `max_symbols`
    as selected+auto-selected, un-marking any previous auto-selection that
    fell out of the ranking. Returns the newly chosen symbols. Manual
    selections (`is_auto_selected=False`) are never touched.
    """
    tickers = binance_client.get_ticker_24hr()  # no symbol -> every pair, one call

    eligible_rows = {
        row.symbol: row
        for row in db.query(Symbol).filter(Symbol.quote_asset == "USDT", Symbol.status == "TRADING").all()
    }

    candidates: list[tuple[str, float]] = []
    for t in tickers:
        symbol = t.get("symbol")
        if symbol not in eligible_rows:
            continue
        try:
            quote_volume = float(t.get("quoteVolume", 0.0))
            price_change_pct = abs(float(t.get("priceChangePercent", 0.0)))
        except (TypeError, ValueError):
            continue
        if quote_volume < min_volume_usdt:
            continue
        if price_change_pct > MAX_PRICE_CHANGE_PCT_24H:
            continue
        candidates.append((symbol, price_change_pct))

    candidates.sort(key=lambda item: item[1], reverse=True)

    chosen: list[str] = []
    skipped_stuck: list[str] = []
    skipped_cooldown: list[str] = []
    for symbol, _ in candidates:
        if len(chosen) >= max_symbols:
            break
        if _is_stuck_in_extreme_volatility(db, symbol):
            skipped_stuck.append(symbol)
            continue
        if _in_rotation_cooldown(db, symbol):
            skipped_cooldown.append(symbol)
            continue
        chosen.append(symbol)

    if skipped_stuck:
        logger.info("Skipped candidates still classified EXTREME_VOLATILITY: %s", skipped_stuck)
    if skipped_cooldown:
        logger.info("Skipped candidates still in rotation cooldown (traded recently): %s", skipped_cooldown)

    previously_auto = db.query(Symbol).filter(Symbol.is_auto_selected.is_(True)).all()
    for row in previously_auto:
        # Never deselect a symbol with a live position - see
        # _in_rotation_cooldown's docstring on why that would orphan it.
        if row.symbol not in chosen and not _has_open_position(db, row.symbol):
            row.is_selected = False
            row.is_auto_selected = False

    for symbol in chosen:
        row = eligible_rows[symbol]
        row.is_selected = True
        row.is_auto_selected = True

    if chosen:
        logger.info("Auto-selected symbols: %s", chosen)
    else:
        logger.warning("Auto symbol selection found no liquid USDT pair clearing min_volume_usdt=%s", min_volume_usdt)

    return chosen
