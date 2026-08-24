from __future__ import annotations

from binmarket_shared.quant import indicators as ind
from binmarket_shared.quant.costs import estimate_spread_pct, estimate_trade_economics
from binmarket_shared.quant.regime import RegimeReading, VolatilityRegime
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


class BreakoutStrategy(BaseStrategy):
    name = "breakout"
    version = "1.0.0"
    description = "Entra cuando el precio rompe una resistencia reciente con confirmación de volumen."
    default_params = {
        "lookback_bars": 20,
        "breakout_buffer_pct": 0.1,
        "volume_multiplier": 1.5,
        "atr_period": 14,
        "atr_stop_multiplier": 1.8,
        "take_profit_rr": 2.2,
        "min_opportunity_score": 65.0,
        "deterioration_exit_score": 35.0,
    }

    def is_regime_eligible(self, regime: RegimeReading) -> bool:
        return regime.volatility in (VolatilityRegime.NORMAL, VolatilityRegime.HIGH)

    def _resistance_level(self, ctx: StrategyContext) -> float:
        lookback = self.params["lookback_bars"]
        highs = ctx.df["high"].iloc[-(lookback + 1):-1]
        return float(highs.max()) if len(highs) else ctx.current_price

    def _snapshot(self, ctx: StrategyContext) -> IndicatorSnapshot:
        df = ctx.df
        close = df["close"]
        ema_fast = ind.ema(close, 20)
        ema_slow = ind.ema(close, 50)
        rsi = ind.rsi(close, 14)
        macd_df = ind.macd(close)
        bb = ind.bollinger_bands(close)
        atr_series = ind.atr(df, self.params["atr_period"])
        adx_series = ind.adx(df, self.params["atr_period"])
        vol_sma = ind.volume_sma(df)

        return IndicatorSnapshot(
            close=float(close.iloc[-1]),
            ema_fast=float(ema_fast.iloc[-1]),
            ema_slow=float(ema_slow.iloc[-1]),
            ema_fast_slope_pct=0.0,
            rsi=float(rsi.iloc[-1]),
            macd_histogram=float(macd_df["histogram"].iloc[-1]),
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
        resistance = self._resistance_level(ctx)

        breakout_pct = (snap.close - resistance) / resistance * 100 if resistance else 0.0
        volume_ratio = snap.volume / snap.volume_sma if snap.volume_sma else 0.0

        trend_score, r_trend = score_trend(snap, "LONG")
        volume_score, r_vol = score_volume(snap)
        volatility_score, r_volat = score_volatility(snap)

        breakout_score = clip(50 + breakout_pct * 30)
        reasons_b = [f"Ruptura de resistencia de {p['lookback_bars']} velas ({breakout_pct:+.2f}%)"]
        if volume_ratio >= p["volume_multiplier"]:
            breakout_score = clip(breakout_score + 20)
            reasons_b.append(f"Volumen confirma la ruptura ({volume_ratio:.1f}x el promedio)")

        entry_price = ctx.current_price
        atr_abs = snap.atr_pct / 100 * entry_price
        stop_loss = min(resistance, entry_price - atr_abs * p["atr_stop_multiplier"])
        take_profit = entry_price + (entry_price - stop_loss) * p["take_profit_rr"]

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

        opportunity_score = combine_scores(
            trend_score, breakout_score, volume_score, volatility_score, risk_score,
            weights={"trend": 0.15, "momentum": 0.30, "volume": 0.20, "volatility": 0.15, "risk": 0.20},
        )
        reasons = reasons_b + r_trend + r_vol + r_volat + r_risk

        scores = ScoreBreakdown(trend_score, breakout_score, volume_score, volatility_score, risk_score, opportunity_score, reasons)

        if ctx.open_position is not None:
            return StrategySignal("HOLD", scores, reasons + ["Ya existe una posición abierta en este símbolo"])

        if not self.is_regime_eligible(ctx.regime):
            return StrategySignal(
                "NO_TRADE", scores, reasons + [f"Régimen actual ({ctx.regime.label}) no favorable para Breakout"]
            )

        if breakout_pct <= p["breakout_buffer_pct"] or volume_ratio < p["volume_multiplier"]:
            return StrategySignal(
                "NO_TRADE", scores, reasons + ["No hay ruptura confirmada con volumen suficiente todavía"],
            )

        if economics.net_profit_pct < ctx.min_expected_net_profit_pct:
            return StrategySignal(
                "NO_TRADE",
                scores,
                reasons + [f"Ganancia neta esperada {economics.net_profit_pct:.2f}% insuficiente tras costos"],
                entry_price, stop_loss, take_profit, None, economics.net_profit_pct, economics.risk_reward_ratio,
            )

        action = "BUY" if opportunity_score >= p["min_opportunity_score"] else "HOLD"

        return StrategySignal(
            action, scores, reasons, entry_price, stop_loss, take_profit, None,
            economics.net_profit_pct, economics.risk_reward_ratio,
        )

    def should_exit_on_deterioration(self, ctx: StrategyContext) -> tuple[bool, str | None]:
        if ctx.open_position is None:
            return False, None
        resistance = self._resistance_level(ctx)
        if ctx.current_price < resistance:
            return True, "Ruptura fallida: el precio volvió a caer por debajo del nivel de resistencia"
        return False, None
