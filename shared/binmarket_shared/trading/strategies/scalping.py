from __future__ import annotations

from binmarket_shared.quant import indicators as ind
from binmarket_shared.quant.costs import estimate_spread_pct, estimate_trade_economics
from binmarket_shared.quant.regime import RegimeReading, VolatilityRegime
from binmarket_shared.quant.scoring import (
    IndicatorSnapshot,
    ScoreBreakdown,
    combine_scores,
    score_momentum,
    score_risk,
    score_trend,
    score_volatility,
    score_volume,
)

from .base import BaseStrategy, StrategyContext, StrategySignal


class ScalpingStrategy(BaseStrategy):
    """High-frequency, small-target strategy (requested directly by the
    user): many small wins a day instead of a few large ones. It still goes
    through the exact same cost gate and Risk Manager as every other
    strategy — a small take-profit does not mean the trade skips the "is
    this actually worth it after fees/spread/slippage" check, and a
    stop-loss is always set. No strategy in this system is allowed to
    promise it will "always win"; this one just aims small and often.
    """

    name = "scalping"
    version = "1.0.0"
    description = (
        "Muchas operaciones chicas por día: entra en micro-impulsos de corto plazo (5m) y "
        "cierra apenas alcanza una ganancia neta pequeña y configurable, con stop-loss ajustado."
    )
    preferred_timeframe = "5m"
    default_params = {
        "ema_fast": 9,
        "ema_slow": 21,
        "rsi_period": 14,
        "take_profit_pct": 0.5,
        "stop_loss_pct": 0.6,
        "min_opportunity_score": 55.0,
        "max_entry_rsi": 70.0,
        "min_entry_rsi": 35.0,
        "deterioration_exit_score": 35.0,
    }

    @property
    def min_bars_required(self) -> int:
        return 30  # EMA9/21 + RSI14 need much less warmup than the 1h strategies

    def is_regime_eligible(self, regime: RegimeReading) -> bool:
        # LOW volatility: not enough movement to clear costs with a small
        # target. EXTREME: too whippy for a tight stop. Any trend direction
        # is fine — scalping looks for micro-moves, not the macro trend.
        return regime.volatility in (VolatilityRegime.NORMAL, VolatilityRegime.HIGH)

    def _snapshot(self, ctx: StrategyContext) -> IndicatorSnapshot:
        p = self.params
        df = ctx.df
        close = df["close"]
        ema_fast = ind.ema(close, p["ema_fast"])
        ema_slow = ind.ema(close, p["ema_slow"])
        rsi = ind.rsi(close, p["rsi_period"])
        macd_df = ind.macd(close, fast=6, slow=13, signal=5)
        bb = ind.bollinger_bands(close, period=20)
        atr_series = ind.atr(df, 14)
        adx_series = ind.adx(df, 14)
        vol_sma = ind.volume_sma(df, period=20)

        slope_pct = 0.0
        if len(ema_fast) > 4 and ema_fast.iloc[-4] not in (0, None):
            slope_pct = (ema_fast.iloc[-1] - ema_fast.iloc[-4]) / ema_fast.iloc[-4] * 100

        return IndicatorSnapshot(
            close=float(close.iloc[-1]),
            ema_fast=float(ema_fast.iloc[-1]),
            ema_slow=float(ema_slow.iloc[-1]),
            ema_fast_slope_pct=float(slope_pct),
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

        trend_score, r_trend = score_trend(snap, "LONG")
        momentum_score, r_mom = score_momentum(snap, "LONG")
        volume_score, r_vol = score_volume(snap)
        volatility_score, r_volat = score_volatility(snap)

        entry_price = ctx.current_price
        stop_loss = entry_price * (1 - p["stop_loss_pct"] / 100)
        take_profit = entry_price * (1 + p["take_profit_pct"] / 100)

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

        # Momentum and volume matter most here: we're betting on an
        # immediate micro-move actually happening, not on a macro trend.
        opportunity_score = combine_scores(
            trend_score, momentum_score, volume_score, volatility_score, risk_score,
            weights={"trend": 0.20, "momentum": 0.35, "volume": 0.20, "volatility": 0.10, "risk": 0.15},
        )
        reasons = r_trend + r_mom + r_vol + r_volat + r_risk

        scores = ScoreBreakdown(trend_score, momentum_score, volume_score, volatility_score, risk_score, opportunity_score, reasons)

        if ctx.open_position is not None:
            return StrategySignal("HOLD", scores, reasons + ["Ya existe una posición abierta en este símbolo"])

        if not self.is_regime_eligible(ctx.regime):
            return StrategySignal(
                "NO_TRADE", scores, reasons + [f"Régimen actual ({ctx.regime.label}) no favorable para Scalping"]
            )

        if economics.net_profit_pct < ctx.min_expected_net_profit_pct:
            return StrategySignal(
                "NO_TRADE",
                scores,
                reasons + [
                    f"Ganancia neta esperada {economics.net_profit_pct:.3f}% por debajo del mínimo configurado "
                    f"({ctx.min_expected_net_profit_pct:.3f}%) — el objetivo de {p['take_profit_pct']}% no alcanza "
                    "a cubrir comisiones/spread/slippage con margen suficiente"
                ],
                entry_price, stop_loss, take_profit, None, economics.net_profit_pct, economics.risk_reward_ratio,
            )

        rsi_in_range = p["min_entry_rsi"] <= snap.rsi <= p["max_entry_rsi"]
        aligned = snap.ema_fast > snap.ema_slow

        if opportunity_score >= p["min_opportunity_score"] and aligned and rsi_in_range:
            action = "BUY"
        elif opportunity_score >= p["min_opportunity_score"] * 0.7:
            action = "HOLD"
            reasons.append("Score insuficiente o RSI fuera de rango todavía para entrar")
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
        if snap.ema_fast < snap.ema_slow:
            return True, "Micro-tendencia (5m) se invirtió: EMA rápida cayó por debajo de la EMA lenta"
        momentum_score, _ = score_momentum(snap, "LONG")
        if momentum_score < self.params["deterioration_exit_score"]:
            return True, f"Momentum de corto plazo deteriorado ({momentum_score:.0f}/100)"
        return False, None
