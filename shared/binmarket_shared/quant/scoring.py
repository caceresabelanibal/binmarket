"""Signal scoring system (section 10 of the spec).

Produces five 0-100 sub-scores (trend, momentum, volume, volatility, risk)
plus a weighted `opportunity_score`, and a human-readable list of reasons —
this is what powers the "why did it buy?" Decision Log. The weights below are
a documented heuristic starting point (see docs/strategy.md); they are meant
to be tuned through backtesting, not treated as a proven optimum.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Direction = Literal["LONG", "SHORT"]


def clip(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


# Internal alias kept for brevity in this module's own function bodies.
_clip = clip


@dataclass
class IndicatorSnapshot:
    close: float
    ema_fast: float
    ema_slow: float
    ema_fast_slope_pct: float
    rsi: float
    macd_histogram: float
    bb_upper: float
    bb_mid: float
    bb_lower: float
    bb_width_pct: float
    atr_pct: float
    adx: float
    volume: float
    volume_sma: float


@dataclass
class ScoreBreakdown:
    trend_score: float
    momentum_score: float
    volume_score: float
    volatility_score: float
    risk_score: float
    opportunity_score: float
    reasons: list[str] = field(default_factory=list)


def score_trend(snap: IndicatorSnapshot, direction: Direction = "LONG") -> tuple[float, list[str]]:
    reasons: list[str] = []
    gap_pct = ((snap.ema_fast - snap.ema_slow) / snap.ema_slow) * 100 if snap.ema_slow else 0.0
    aligned = gap_pct > 0 if direction == "LONG" else gap_pct < 0
    slope_aligned = snap.ema_fast_slope_pct > 0 if direction == "LONG" else snap.ema_fast_slope_pct < 0

    score = 50.0
    score += _clip(abs(gap_pct) * 20, 0, 25) * (1 if aligned else -1)
    score += _clip(min(snap.adx, 40) / 40 * 25, 0, 25) * (1 if aligned else 0.3)
    if slope_aligned:
        score += 10
        reasons.append(f"EMA rápida con pendiente {'positiva' if direction == 'LONG' else 'negativa'}")
    if aligned:
        reasons.append(f"EMA rápida {'>' if direction == 'LONG' else '<'} EMA lenta ({gap_pct:.2f}%)")
    if snap.adx > 25:
        reasons.append(f"ADX {snap.adx:.0f} indica tendencia con fuerza")
    elif snap.adx < 15:
        reasons.append(f"ADX {snap.adx:.0f} indica ausencia de tendencia")
    return _clip(score), reasons


def score_momentum(snap: IndicatorSnapshot, direction: Direction = "LONG") -> tuple[float, list[str]]:
    reasons: list[str] = []
    score = 50.0

    if direction == "LONG":
        rsi_component = _clip((snap.rsi - 50) * 1.6, -40, 40)
        if snap.rsi >= 70:
            score -= 15
            reasons.append(f"RSI {snap.rsi:.0f} en zona de sobrecompra (riesgo de reversión)")
        elif snap.rsi <= 30:
            score -= 10
            reasons.append(f"RSI {snap.rsi:.0f} en zona de sobreventa")
        else:
            reasons.append(f"RSI {snap.rsi:.0f}")
    else:
        rsi_component = _clip((50 - snap.rsi) * 1.6, -40, 40)
        reasons.append(f"RSI {snap.rsi:.0f}")

    score += rsi_component

    macd_aligned = snap.macd_histogram > 0 if direction == "LONG" else snap.macd_histogram < 0
    if macd_aligned:
        score += 15
        reasons.append("MACD histograma " + ("positivo" if direction == "LONG" else "negativo"))
    else:
        score -= 10

    return _clip(score), reasons


def score_volume(snap: IndicatorSnapshot) -> tuple[float, list[str]]:
    reasons: list[str] = []
    if not snap.volume_sma:
        return 50.0, ["Volumen promedio no disponible aún"]
    ratio = snap.volume / snap.volume_sma
    score = _clip(50 + (ratio - 1) * 50)
    if ratio > 1.3:
        reasons.append(f"Volumen {ratio:.1f}x por encima del promedio")
    elif ratio < 0.6:
        reasons.append(f"Volumen {ratio:.1f}x por debajo del promedio (señal más débil)")
    else:
        reasons.append(f"Volumen dentro de rango normal ({ratio:.1f}x)")
    return score, reasons


def score_volatility(snap: IndicatorSnapshot) -> tuple[float, list[str]]:
    """Rewards volatility that is present but not extreme — no movement means
    no opportunity, extreme volatility means unreliable stops/targets."""
    reasons: list[str] = []
    atr_pct = snap.atr_pct
    if atr_pct < 0.15:
        score = 30.0
        reasons.append(f"Volatilidad muy baja (ATR {atr_pct:.2f}% del precio)")
    elif atr_pct <= 2.5:
        # sweet spot, peaking around ~1%
        score = _clip(100 - abs(atr_pct - 1.0) * 25)
        reasons.append(f"Volatilidad aceptable (ATR {atr_pct:.2f}% del precio)")
    else:
        score = _clip(60 - (atr_pct - 2.5) * 15)
        reasons.append(f"Volatilidad elevada (ATR {atr_pct:.2f}% del precio)")
    return score, reasons


def score_risk(
    risk_reward_ratio: float | None,
    expected_net_profit_pct: float | None,
    exposure_pct_after_trade: float,
    max_total_exposure_pct: float,
) -> tuple[float, list[str]]:
    reasons: list[str] = []
    score = 50.0

    if risk_reward_ratio is not None:
        score += _clip((risk_reward_ratio - 1.5) * 20, -30, 30)
        reasons.append(f"Relación riesgo/beneficio {risk_reward_ratio:.1f}")
    else:
        score -= 10

    if expected_net_profit_pct is not None:
        score += _clip(expected_net_profit_pct * 10, -20, 20)
        reasons.append(f"Ganancia neta esperada {expected_net_profit_pct:.2f}% tras comisiones/slippage")

    exposure_headroom = max_total_exposure_pct - exposure_pct_after_trade
    if exposure_headroom < 0:
        score -= 30
        reasons.append("Excede el límite de exposición total configurado")
    elif exposure_headroom < max_total_exposure_pct * 0.15:
        score -= 10
        reasons.append("Exposición total se acerca al límite configurado")

    return _clip(score), reasons


def combine_scores(
    trend_score: float,
    momentum_score: float,
    volume_score: float,
    volatility_score: float,
    risk_score: float,
    weights: dict[str, float] | None = None,
) -> float:
    w = weights or {"trend": 0.30, "momentum": 0.25, "volume": 0.15, "volatility": 0.15, "risk": 0.15}
    total = (
        trend_score * w["trend"]
        + momentum_score * w["momentum"]
        + volume_score * w["volume"]
        + volatility_score * w["volatility"]
        + risk_score * w["risk"]
    )
    return round(_clip(total), 1)
