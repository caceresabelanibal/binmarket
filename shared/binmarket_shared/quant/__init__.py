"""Pure, stateless market analysis primitives: indicators, regime detection,
signal scoring, cost modelling and position sizing.

Nothing in this package touches the database, Binance, or order execution —
that separation is intentional (section 9 of the spec: "no acoplar los
indicadores directamente al código de ejecución de órdenes"). It is imported
by both the trading-engine (live loop) and the backend (on-demand backtests
and manual-trading previews), so there is exactly one implementation of every
indicator/strategy/cost calculation in the whole system.
"""
