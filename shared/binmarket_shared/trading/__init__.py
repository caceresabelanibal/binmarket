"""Strategy, risk, execution, order-management, backtest and AI-advisor layers.

Built on top of `binmarket_shared.quant`. This is where "should we trade"
decisions are made; nothing here talks to Binance or the DB directly except
the `execution` and `orders` submodules, which are the only two places
allowed to write orders/positions/trades.
"""
