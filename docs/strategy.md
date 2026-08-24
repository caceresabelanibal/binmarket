# Estrategias y sistema de señales

## Arquitectura de plugins

Toda estrategia extiende `BaseStrategy` (`shared/binmarket_shared/trading/strategies/base.py`) e implementa:

- `is_regime_eligible(regime)`: si la estrategia debería considerarse en el régimen de mercado actual.
- `generate_signal(ctx)`: mirando únicamente `ctx.df` hasta la barra actual (nunca datos futuros), devuelve un `StrategySignal` con acción, scores y razones.
- `should_exit_on_deterioration(ctx)` (opcional): condición de salida específica de la estrategia, además de los stop-loss/take-profit/trailing genéricos que gestiona el engine loop.

Agregar una estrategia nueva es: crear el archivo, registrar la clase en `registry.py`. Nada más del sistema necesita cambiar.

## Régimen de mercado (`quant/regime.py`)

Clasifica cada símbolo en un régimen de tendencia (`STRONG_UPTREND`, `UPTREND`, `SIDEWAYS`, `DOWNTREND`, `STRONG_DOWNTREND`) y uno de volatilidad (`LOW`, `NORMAL`, `HIGH`, `EXTREME`), usando EMA20/EMA50, ADX14 y volatilidad realizada. `EXTREME_VOLATILITY` marca el régimen como no operable (`RegimeReading.is_tradeable == False`) independientemente de qué diga cualquier estrategia.

## Estrategias incluidas

| Estrategia | Elegible cuando | Lógica de entrada |
|---|---|---|
| `trend_following` | UPTREND o STRONG_UPTREND, volatilidad no extrema | EMA rápida > EMA lenta, RSI en rango 38-75, ADX confirma fuerza, MACD positivo |
| `mean_reversion` | SIDEWAYS, volatilidad baja/normal | Precio en/bajo banda inferior de Bollinger, RSI ≤ 40 (sobreventa) |
| `breakout` | Volatilidad normal/alta (cualquier tendencia) | Ruptura de la resistencia de N velas con volumen ≥ 1.5x el promedio |

Todos son estrategias **long-only** (spot): no hay short selling.

## Sistema de scoring (`quant/scoring.py`)

Cinco sub-scores de 0 a 100 (`trend`, `momentum`, `volume`, `volatility`, `risk`) se combinan en un `opportunity_score` ponderado. Los pesos son un punto de partida heurístico documentado en el propio código — están pensados para ajustarse mediante backtesting, no como un óptimo demostrado. Cada sub-score viene acompañado de una lista de razones en lenguaje natural, que es lo que alimenta el **Decision Log**.

## Modelo de costos y el gate de rentabilidad (sección 13)

Antes de que cualquier señal BUY se convierta en orden, `quant/costs.py` calcula:

```
expected_net_profit = ganancia_bruta_esperada − comisión_ida_y_vuelta − spread − slippage
```

Si `expected_net_profit < min_expected_net_profit_pct` (configurable), la señal se marca `NO_TRADE` con la razón explícita — nunca se ejecuta una operación solo porque "el precio subió/bajó".

## Position sizing (sección 11)

`quant/position_sizing.py` deriva la cantidad a partir del riesgo asumido (no de un monto fijo): `riesgo_usdt / distancia_al_stop`, luego recortado por `max_position_size_pct` y por el presupuesto de exposición restante (`max_total_exposure_pct`), y finalmente redondeado a los filtros reales de Binance (`LOT_SIZE`, `MIN_NOTIONAL`). Si después de todo esto la cantidad es inválida, la operación se rechaza — nunca se redondea "hacia arriba" para forzar una operación.

## Backtesting y walk-forward (secciones 15/16)

`trading/backtest/engine.py` simula barra por barra, exponiendo a la estrategia únicamente `df.iloc[:i+1]` en cada paso (sin look-ahead), cobrando comisión y slippage en cada fill. Métricas: ROI, win rate, profit factor, Sharpe, max drawdown, mejor/peor operación, duración promedio, curva de equity.

`trading/backtest/walk_forward.py` divide el rango solicitado en N ventanas out-of-sample consecutivas y corre el motor de backtest (con los mismos parámetros fijos) en cada una — útil para detectar si una estrategia se degrada fuera de la muestra original, aunque no re-optimiza parámetros por ventana (ver `docs/architecture.md`, sección de simplificaciones).

## IA (sección 27)

`trading/ai/advisor.py` define el contrato `AIAdvisor.recommend(ctx, strategy_signal) -> AIRecommendation` (acción, confianza, tamaño sugerido, stop/take-profit, razones). `RuleBasedAdvisor` es la implementación de referencia (sin LLM). La recomendación siempre pasa por el Risk Manager antes de convertirse en una orden — ninguna implementación futura de este contrato puede saltarse ese paso.
