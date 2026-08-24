from __future__ import annotations

from binmarket_shared.quant import indicators as ind
from binmarket_shared.quant.costs import estimate_spread_pct, estimate_trade_economics
from binmarket_shared.quant.regime import RegimeReading, TrendRegime, VolatilityRegime
from binmarket_shared.quant.scoring import (
    IndicatorSnapshot,
    ScoreBreakdown,
    clip,
    combine_scores,
    score_risk,
    score_trend,
    score_volatility,
    score_volume,
)

from .base import BaseStrategy, StrategyContext, StrategySignal


def _score_reversion_momentum(snap: IndicatorSnapshot) -> tuple[float, list[str]]:
    reasons: list[str] = []
    if snap.rsi <= 20:
        score = 95.0
    elif snap.rsi <= 30:
        score = 80.0
    elif snap.rsi <= 40:
        score = 55.0
    else:
        score = 25.0
    reasons.append(f"RSI {snap.rsi:.0f}" + (" (sobreventa, favorable para reversión)" if snap.rsi <= 35 else ""))

    if snap.bb_lower:
        distance_pct = (snap.close - snap.bb_lower) / snap.bb_lower * 100
        if distance_pct <= 0.1:
            score = min(100.0, score + 15)
            reasons.append("Precio en o por debajo de la banda inferior de Bollinger")
    return clip(score), reasons


class MeanReversionStrategy(BaseStrategy):
    name = "mean_reversion"
    version = "1.0.0"
    description = "Opera reversiones a la media en mercados laterales usando Bandas de Bollinger y RSI."
    default_params = {
        "bb_period": 20,
        "bb_std": 2.0,
        "rsi_period": 14,
        "atr_period": 14,
        "atr_stop_multiplier": 1.5,
        "min_opportunity_score": 62.0,
        "max_entry_rsi": 40.0,
        "deterioration_exit_score": 35.0,
    }

    def is_regime_eligible(self, regime: RegimeReading) -> bool:
        return regime.trend == TrendRegime.SIDEWAYS and regime.volatility in (
            VolatilityRegime.LOW,
            VolatilityRegime.NORMAL,
        )

    def _snapshot(self, ctx: StrategyContext) -> IndicatorSnapshot:
        p = self.params
        df = ctx.df
        close = df["close"]
        ema_fast = ind.ema(close, 20)
        ema_slow = ind.ema(close, 50)
        rsi = ind.rsi(close, p["rsi_period"])
        bb = ind.bollinger_bands(close, p["bb_period"], p["bb_std"])
        atr_series = ind.atr(df, p["atr_period"])
        adx_series = ind.adx(df, p["atr_period"])
        vol_sma = ind.volume_sma(df)

        return IndicatorSnapshot(
            close=float(close.iloc[-1]),
            ema_fast=float(ema_fast.iloc[-1]),
            ema_slow=float(ema_slow.iloc[-1]),
            ema_fast_slope_pct=0.0,
            rsi=float(rsi.iloc[-1]),
            macd_histogram=0.0,
            bb_upper=float(bb["upper"].iloc[-1]),
            bb_mid=float(bb["mid"].iloc[-1]),
            bb_lower=float(bb["lower"].iloc[-1]),
            bb_width_pct=float(bb["width_pct"].iloc[-1]) if not bb["width_pct"].isna().iloc[-1] else 0.0,
            atr_pct=float(atr_series.iloc[-1] / close.iloc[-1] * 100) if close.iloc[-1] else 0.0,
            adx=float(adx_series.iloc[-1]),
            volume=float(df["volume"].iloc[-1]),
            volume_sma=float(vol_sma.iloc[-1]) if not vol_sma.isna().iloc[-1] else 0.0,
        )

    def generate_signal(self, ctx: StrategyContext) -> StrategySignal:
        p = self.params
        snap = self._snapshot(ctx)

        trend_score, r_trend = score_trend(snap, "LONG")
        reversion_score, r_mom = _score_reversion_momentum(snap)
        volume_score, r_vol = score_volume(snap)
        volatility_score, r_volat = score_volatility(snap)

        entry_price = ctx.current_price
        atr_abs = snap.atr_pct / 100 * entry_price
        stop_loss = entry_price - atr_abs * p["atr_stop_multiplier"]
        take_profit = max(snap.bb_mid, entry_price * 1.001)

        spread_pct = estimate_spread_pct(ctx.best_bid or entry_price, ctx.best_ask or entry_price)
        economics = estimate_trade_economics(
            entry_price, take_profit, stop_loss, ctx.taker_fee_pct, spread_pct, ctx.default_slippage_pct
        )

        assumed_position_value = ctx.available_capital * (ctx.max_position_size_pct / 100)
        exposure_after_pct = (
            (ctx.current_total_exposure_value + assumed_position_value) / max(ctx.available_capital, 1e-9) * 100
        )
        risk_score, r_risk = score_risk(
            economics.risk_reward_ratio, economics.net_profit_pct, exposure_after_pct, ctx.max_total_exposure_pct
        )

        # For mean reversion, weigh reversion-momentum and volatility more than
        # trend strength (a strong trend is actually a warning sign here).
        opportunity_score = combine_scores(
            trend_score, reversion_score, volume_score, volatility_score, risk_score,
            weights={"trend": 0.10, "momentum": 0.35, "volume": 0.15, "volatility": 0.20, "risk": 0.20},
        )
        reasons = r_trend + r_mom + r_vol + r_volat + r_risk

        scores = ScoreBreakdown(trend_score, reversion_score, volume_score, volatility_score, risk_score, opportunity_score, reasons)

        if ctx.open_position is not None:
            return StrategySignal("HOLD", scores, reasons + ["Ya existe una posición abierta en este símbolo"])

        if not self.is_regime_eligible(ctx.regime):
            return StrategySignal(
                "NO_TRADE", scores, reasons + [f"Régimen actual ({ctx.regime.label}) no favorable para Mean Reversion"]
            )

        if economics.net_profit_pct < ctx.min_expected_net_profit_pct:
            return StrategySignal(
                "NO_TRADE",
                scores,
                reasons + [f"Ganancia neta esperada {economics.net_profit_pct:.2f}% insuficiente tras costos"],
                entry_price, stop_loss, take_profit, None, economics.net_profit_pct, economics.risk_reward_ratio,
            )

        if opportunity_score >= p["min_opportunity_score"] and snap.rsi <= p["max_entry_rsi"]:
            action = "BUY"
        elif opportunity_score >= p["min_opportunity_score"] * 0.7:
            action = "HOLD"
            reasons.append("Aún no se cumplen todas las condiciones de sobreventa para entrar")
        else:
            action = "NO_TRADE"
            reasons.append("Condiciones de entrada no se cumplen")

        return StrategySignal(
            action, scores, reasons, entry_price, stop_loss, take_profit, None,
            economics.net_profit_pct, economics.risk_reward_ratio,
        )

    def should_exit_on_deterioration(self, ctx: StrategyContext) -> tuple[bool, str | None]:
        if ctx.open_position is None:
            return False, None
        snap = self._snapshot(ctx)
        if snap.close >= snap.bb_mid:
            return True, "Precio alcanzó la media de Bollinger (objetivo de reversión cumplido)"
        if snap.rsi >= 60:
            return True, "RSI ya no indica sobreventa: tesis de reversión invalidada"
        return False, None
