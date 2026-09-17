"""market-data/app/ingest.py's order-book snapshot persistence - research
data collection (requested directly by the user after real backtesting
found no exploitable edge in classic 5m candle indicators) so a
forward-return analysis on bid/ask imbalance can be run later, once enough
real history has accumulated.

`_persist_orderbook_snapshot`/`_prune_old_orderbook_snapshots` open their own
`session_scope()` (same as `_upsert_candle`), a real commit on its own
connection - unlike the `db` fixture's writes (isolated in a savepoint that's
always rolled back), so setup data for the prune test is written the same
way the production code writes it, not through `db`.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from binmarket_shared.db.base import session_scope
from binmarket_shared.db.models import OrderbookSnapshot
from binmarket_shared.redis_keys import ORDERBOOK_SNAPSHOT_RETENTION_DAYS

from ._service_import import import_service_module

_ingest = import_service_module("market-data", "ingest")
_persist_orderbook_snapshot = _ingest._persist_orderbook_snapshot
_prune_old_orderbook_snapshots = _ingest._prune_old_orderbook_snapshots


def test_persists_a_snapshot_with_computed_imbalance(db):
    bids = [["100.0", "3.0"], ["99.9", "1.0"]]
    asks = [["100.1", "1.0"], ["100.2", "1.0"]]

    _persist_orderbook_snapshot("BTCUSDT", bids, asks)

    row = (
        db.query(OrderbookSnapshot)
        .filter(OrderbookSnapshot.symbol == "BTCUSDT")
        .order_by(OrderbookSnapshot.id.desc())
        .first()
    )
    assert row is not None
    assert row.best_bid == 100.0
    assert row.best_ask == 100.1
    assert row.mid_price == pytest.approx(100.05)
    assert row.bid_volume_top5 == 4.0
    assert row.ask_volume_top5 == 2.0
    assert row.imbalance_pct == pytest.approx(33.333, rel=1e-3)  # (4-2)/(4+2)*100


def test_zero_total_volume_does_not_divide_by_zero(db):
    _persist_orderbook_snapshot("ZEROUSDT", [["1.0", "0.0"]], [["1.1", "0.0"]])

    row = (
        db.query(OrderbookSnapshot)
        .filter(OrderbookSnapshot.symbol == "ZEROUSDT")
        .order_by(OrderbookSnapshot.id.desc())
        .first()
    )
    assert row.imbalance_pct == 0.0


def test_prune_removes_only_snapshots_older_than_the_retention_window(db):
    with session_scope() as setup_db:
        old = OrderbookSnapshot(
            symbol="OLDUSDT", best_bid=1, best_ask=1, mid_price=1,
            bid_volume_top5=1, ask_volume_top5=1, imbalance_pct=0,
        )
        setup_db.add(old)
        setup_db.flush()
        old.captured_at = datetime.now(timezone.utc) - timedelta(days=ORDERBOOK_SNAPSHOT_RETENTION_DAYS + 1)

        setup_db.add(OrderbookSnapshot(
            symbol="RECENTUSDT", best_bid=1, best_ask=1, mid_price=1,
            bid_volume_top5=1, ask_volume_top5=1, imbalance_pct=0,
        ))

    _prune_old_orderbook_snapshots()

    assert db.query(OrderbookSnapshot).filter(OrderbookSnapshot.symbol == "OLDUSDT").first() is None
    assert db.query(OrderbookSnapshot).filter(OrderbookSnapshot.symbol == "RECENTUSDT").first() is not None
