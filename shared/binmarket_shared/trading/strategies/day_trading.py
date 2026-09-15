"""Day-trading strategy (requested directly by the user), three phases:

1. Weekly context: hour-of-day seasonality (quant/seasonality.py) computed
   from the last 7 days of 1h candles - "does this hour historically tend
   to go up for this symbol?"
2. Daily context: the same 1h series' last 24 bars feed the usual
   trend/momentum/volume/volatility scoring every other strategy uses -
   "is today's actual price action confirming that?"
3. Real-time execution: entries only fire when the current hour's
   historical bias AND live technical confirmation both agree, sized and
   risk-checked exactly like every other strategy (this never bypasses the
   Risk Manager or the cost gate). Positions are flattened before end of
   day regardless of stop-loss/take-profit status - no overnight exposure.

`preferred_timeframe = "1h"` is deliberate, not a placeholder: it's the same
series already loaded for regime classification (up to ~300 hours, comfortably
more than the 7 days of weekly context this needs), so this strategy needs no
extra data-loading plumbing in the engine loop or the backtester - it's a
pure function of the same `ctx.df` every other 1h strategy already gets.
"""
from __future__ import annotations

from binmarket_shared.quant import indicators as ind
from binmarket_shared.quant.costs import estimate_spread_pct, estimate_trade_economics
from binmarket_shared.quant.regime import RegimeReading, VolatilityRegime
from binmarket_shared.quant.scoring import (
    IndicatorSnapshot,
    ScoreBreakdown,
    clip,
    combine_scores,
    score_momentum,
    score_risk,
    score_trend,
    score_volatility,
    score_volume,
)
from binmarket_shared.quant.seasonality import hourly_edge

from .base import BaseStrategy, StrategyContext, StrategySignal

WEEKLY_LOOKBACK_DAYS = 7


class DayTradingStrategy(BaseStrategy):
    name = "day_trading"
    version = "1.0.0"
    description = (
        "Combina contexto semanal (mejor hora histórica del símbolo) y diario (momentum de "
        "las últimas 24h) para decidir cuándo entrar; cierra todas las posiciones antes de fin "
        "de día, sin dejar nada abierto de un día para el otro."
    )
    preferred_timeframe = "1h"
    default_params = {
        "ema_fast": 9,
        "ema_slow": 21,
        "rsi_period": 14,
        "atr_period": 14,
        # Sized for an intraday round-trip, not a multi-day swing: a 2:1 R:R
        # on a wide ATR target combined with a same-day forced flatten meant
        # most trades never got anywhere near take-profit before being cut
        # off - they just rode the full stop-loss risk without collecting
        # the reward that was supposed to offset it. A real backtest over
        # 540 days of ETHUSDT/BTCUSDT 1h data showed this exact failure mode
        # (roughly double trend_following's losses on the same data). Tighter
        # stop + a target that can plausibly be reached within the remaining
        # hours of the day fixes the mismatch.
        "atr_stop_multiplier": 1.0,
        "take_profit_rr": 1.5,
        "min_opportunity_score": 72.0,
        "max_entry_rsi": 68.0,
        "min_entry_rsi": 40.0,
        "deterioration_exit_score": 35.0,
        # Max points (+/-) the hour-of-day seasonality read can shift the
        # trend score - a real signal, not the whole decision by itself.
        "seasonality_weight_pts": 20.0,
        # Requires a genuinely positive historical bias for this hour, not
        # merely "not clearly negative" - the looser version let seasonality
        # wave almost everything through, which is most of why the strategy
        # overtraded (671 trades/540 days on ETHUSDT in backtesting, ~2.5x
        # trend_following's rate on the same data).
        "min_seasonality_edge_pct": 0.02,
        # A positive average with only 1-2 historical samples is close to
        # noise, not an edge - require at least this many observed
        # occurrences of the current hour before trusting it as confirmation.
        "min_seasonality_samples": 3,
        "weekly_lookback_days": WEEKLY_LOOKBACK_DAYS,
        # Flatten everything at/after this UTC hour - no position survives
        # to the next day regardless of its own stop-loss/take-profit.
        "eod_flatten_hour_utc": 23,
        # Don't open a new position if fewer than this many hours remain
        # before the EOD flatten - a trade opened with 1 hour of runway left
        # gets force-closed almost immediately regardless of how it's doing,
        # which is pure noise, not a decision.
        "min_hours_before_eod_entry": 4,
    }

    @property
    def min_bars_required(self) -> int:
        # Same floor as the other 1h strategies (trend_following/mean_reversion
        # /breakout all default to BaseStrategy's 60) - the original 30 let
        # this strategy start trading on indicators (EMA21/ADX/ATR) that
        # hadn't stabilized yet, contributing to the overtrading problem
        # found in backtesting.
        return 60

    def is_regime_eligible(self, regime: RegimeReading) -> bool:
        # Any trend direction is fine - the seasonality+momentum read below
        # is what actually decides whether *now* is a good time, not the
        # broader trend regime. Extreme volatility is still a hard no.
        return regime.volatility != VolatilityRegime.EXTREME

    def _snapshot(self, ctx: StrategyContext) -> IndicatorSnapshot:
        p = self.params
        df = ctx.df
        close = df["close"]
        ema_fast = ind.ema(close, p["ema_fast"])
        ema_slow = ind.ema(close, p["ema_slow"])
        rsi = ind.rsi(close, p["rsi_period"])
        macd_df = ind.macd(close)
        bb = ind.bollinger_bands(close)
        atr_series = ind.atr(df, p["atr_period"])
        adx_series = ind.adx(df, p["atr_period"])
        vol_sma = ind.volume_sma(df)

        slope_pct = 0.0
        if len(ema_fast) > 6 and ema_fast.iloc[-6] not in (0, None):
            slope_pct = (ema_fast.iloc[-1] - ema_fast.iloc[-6]) / ema_fast.iloc[-6] * 100

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

    def _seasonality_reason(self, edge, weight_pts: float) -> tuple[float, str]:
        if edge.sample_count == 0:
            return 0.0, f"Sin historial todavía para la hora {edge.hour_utc}:00 UTC"
        adj = clip(edge.avg_return_pct * 15, -weight_pts, weight_pts)
        confidence = "" if edge.sample_count >= 5 else " (pocas muestras, baja confianza)"
        if edge.avg_return_pct > 0.05:
            return adj, f"Hora {edge.hour_utc}:00 UTC históricamente favorable ({edge.avg_return_pct:+.2f}% promedio, {edge.sample_count} muestras){confidence}"
        if edge.avg_return_pct < -0.05:
            return adj, f"Hora {edge.hour_utc}:00 UTC históricamente desfavorable ({edge.avg_return_pct:+.2f}% promedio, {edge.sample_count} muestras){confidence}"
        return adj, f"Sin sesgo horario claro ({edge.avg_return_pct:+.2f}% promedio, {edge.sample_count} muestras){confidence}"

    def generate_signal(self, ctx: StrategyContext) -> StrategySignal:
        p = self.params
        snap = self._snapshot(ctx)

        current_hour = ctx.df.index[-1].hour
        edge = hourly_edge(ctx.df, current_hour, lookback_days=int(p["weekly_lookback_days"]))
        seasonality_adj, seasonality_reason = self._seasonality_reason(edge, p["seasonality_weight_pts"])

        trend_score, r_trend = score_trend(snap, "LONG")
        trend_score = clip(trend_score + seasonality_adj)
        r_trend = r_trend + [seasonality_reason]

        momentum_score, r_mom = score_momentum(snap, "LONG")
        volume_score, r_vol = score_volume(snap)
        volatility_score, r_volat = score_volatility(snap)

        entry_price = ctx.current_price
        atr_abs = snap.atr_pct / 100 * entry_price
        stop_loss = entry_price - atr_abs * p["atr_stop_multiplier"]
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

        opportunity_score = combine_scores(trend_score, momentum_score, volume_score, volatility_score, risk_score)
        reasons = r_trend + r_mom + r_vol + r_volat + r_risk

        scores = ScoreBreakdown(trend_score, momentum_score, volume_score, volatility_score, risk_score, opportunity_score, reasons)

        if ctx.open_position is not None:
            return StrategySignal("HOLD", scores, reasons + ["Ya existe una posición abierta en este símbolo"])

        if not self.is_regime_eligible(ctx.regime):
            return StrategySignal(
                "NO_TRADE", scores, reasons + [f"Régimen actual ({ctx.regime.label}) no favorable para Day Trading"]
            )

        hours_until_eod = int(p["eod_flatten_hour_utc"]) - current_hour
        if hours_until_eod < int(p["min_hours_before_eod_entry"]):
            return StrategySignal(
                "NO_TRADE", scores,
                reasons + [
                    f"Muy cerca del cierre de fin de día (quedan {max(hours_until_eod, 0)}h, se requieren "
                    f"al menos {int(p['min_hours_before_eod_entry'])}h de margen para una entrada nueva)"
                ],
            )

        if economics.net_profit_pct < ctx.min_expected_net_profit_pct:
            return StrategySignal(
                "NO_TRADE",
                scores,
                reasons + [
                    f"Ganancia neta esperada {economics.net_profit_pct:.2f}% por debajo del mínimo configurado "
                    f"({ctx.min_expected_net_profit_pct:.2f}%) tras comisiones/spread/slippage"
                ],
                entry_price, stop_loss, take_profit, None, economics.net_profit_pct, economics.risk_reward_ratio,
            )

        rsi_in_range = p["min_entry_rsi"] <= snap.rsi <= p["max_entry_rsi"]
        aligned = snap.ema_fast > snap.ema_slow
        seasonality_ok = (
            edge.avg_return_pct >= p["min_seasonality_edge_pct"]
            and edge.sample_count >= int(p["min_seasonality_samples"])
        )

        if not seasonality_ok:
            reasons.append(
                "Bloqueado: la hora actual no tiene un sesgo histórico positivo confirmado para este símbolo "
                f"(requiere >= {p['min_seasonality_edge_pct']:.2f}% con al menos "
                f"{int(p['min_seasonality_samples'])} muestras)"
            )

        if opportunity_score >= p["min_opportunity_score"] and aligned and rsi_in_range and seasonality_ok:
            action = "BUY"
        elif opportunity_score >= p["min_opportunity_score"] * 0.7:
            action = "HOLD"
            reasons.append("Score insuficiente, RSI fuera de rango o sesgo horario en contra todavía")
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

        bar_hour = ctx.df.index[-1].hour
        if bar_hour >= int(self.params["eod_flatten_hour_utc"]):
            return True, f"Cierre de fin de día ({bar_hour}:00 UTC) — no se mantienen posiciones de un día para el otro"

        snap = self._snapshot(ctx)
        if snap.ema_fast < snap.ema_slow:
            return True, "Cruce de tendencia: EMA rápida cayó por debajo de la EMA lenta"
        momentum_score, _ = score_momentum(snap, "LONG")
        if momentum_score < self.params["deterioration_exit_score"]:
            return True, f"Momentum deteriorado ({momentum_score:.0f}/100)"
        return False, None
