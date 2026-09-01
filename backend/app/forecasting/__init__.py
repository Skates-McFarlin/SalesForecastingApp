"""Pluggable forecasters and a per-SKU backtest selector.

Each forecaster turns a SKU's monthly history into a per-month forecast with an
uncertainty band; the selector holds out the recent tail, scores the candidates
on it, and keeps the winner per SKU. This is the spine the model competition
(Prophet, seasonal-naive, LightGBM, later Chronos) plugs into - the LLM only
routes/labels, the math here produces every number.
"""
