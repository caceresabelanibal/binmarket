from __future__ import annotations

from app.backtest import PredictionVerdict, summarize_verdicts


def _verdict(verdict: str) -> PredictionVerdict:
    return PredictionVerdict(
        prediction_id="x", symbol="^IXIC", created_at="2026-01-01T00:00:00+00:00", direction="LONG",
        confidence_pct=50.0, price_at_prediction=100.0, price_at_horizon=101.0,
        actual_move_pct=1.0, verdict=verdict,
    )


def test_hit_rate_only_counts_scored_predictions():
    verdicts = [_verdict("CORRECT"), _verdict("CORRECT"), _verdict("WRONG"), _verdict("PENDING"), _verdict("NO_TRADE")]
    summary = summarize_verdicts(verdicts)
    assert summary["scored"] == 3
    assert summary["correct"] == 2
    assert summary["wrong"] == 1
    assert summary["hit_rate_pct"] == 66.7
    assert summary["pending"] == 1
    assert summary["no_trade"] == 1


def test_hit_rate_is_none_when_nothing_scored_yet():
    verdicts = [_verdict("PENDING"), _verdict("NO_TRADE")]
    summary = summarize_verdicts(verdicts)
    assert summary["scored"] == 0
    assert summary["hit_rate_pct"] is None


def test_empty_verdict_list_is_handled():
    summary = summarize_verdicts([])
    assert summary["total_predictions"] == 0
    assert summary["hit_rate_pct"] is None
