"""Shared types and helpers for the forecaster competition."""
from typing import NamedTuple

import numpy as np
import pandas as pd
from scipy.stats import norm

DEFAULT_INTERVAL_WIDTH = 0.8


class Forecast(NamedTuple):
    """A per-month forecast over the horizon. All arrays share length = horizon.

    yhat is the point forecast; low/high are the per-month uncertainty band at
    DEFAULT_INTERVAL_WIDTH. Totals and the summed interval are derived from
    these (see total / aggregate_interval) so every forecaster speaks the same
    units regardless of how it models a series.
    """
    yhat: np.ndarray
    low: np.ndarray
    high: np.ndarray

    @property
    def total(self) -> float:
        return float(np.sum(self.yhat))


def future_index(start_date, horizon):
    """The horizon's month-start timestamps, matching the app's monthly grain."""
    return pd.date_range(start=start_date, periods=horizon, freq="MS")


def aggregate_interval(forecast: Forecast, interval_width=DEFAULT_INTERVAL_WIDTH):
    """Confidence band for the SUMMED forecast, combining monthly spreads in
    quadrature rather than adding them (which assumes every month hits its
    extreme together and produces absurd ranges). Same reasoning as the old
    _aggregate_interval, decoupled from Prophet's model object."""
    total = forecast.total
    try:
        z = norm.ppf(0.5 + interval_width / 2)
        sigmas = (np.asarray(forecast.high) - np.asarray(forecast.low)) / (2 * z)
        spread = z * float(np.sqrt(np.sum(sigmas ** 2)))
    except Exception:  # noqa: BLE001 - fall back to the raw summed bounds
        return float(np.sum(forecast.low)), float(np.sum(forecast.high))
    return max(0.0, total - spread), total + spread


def mae(pred, actual):
    pred = np.asarray(pred, dtype=float)
    actual = np.asarray(actual, dtype=float)
    return float(np.mean(np.abs(pred - actual)))


def monthly_actuals(df_history, start_date, horizon):
    """Actual y for each month of a window, 0 where the file has no row - used
    to score a backtest against what really happened."""
    by_month = {
        d.strftime("%Y-%m"): float(v)
        for d, v in zip(df_history["ds"], df_history["y"])
    }
    wanted = future_index(start_date, horizon).strftime("%Y-%m")
    return np.array([by_month.get(m, 0.0) for m in wanted])


def clip_nonneg(arr):
    """Unit sales can't go negative; clamp per month."""
    return np.clip(np.asarray(arr, dtype=float), a_min=0.0, a_max=None)


def conformal_halfwidths(residuals, horizon, alpha=0.2):
    """Split-conformal interval half-widths from a model's own recent errors.

    Instead of trusting a model's parametric interval (which assumes bell-curve
    errors that sparse retail data violates), take the absolute errors it
    actually made on a held-out fold and use their empirical quantile as the
    band - a distribution-free, coverage-targeting interval. The finite-sample
    correction ((1-alpha)(1+1/n)) is standard split conformal. Widths grow ~sqrt
    with the horizon (uncertainty compounds) while preserving the average level,
    so later months are wider. Returns per-month half-widths, or None if there
    are no residuals to calibrate from."""
    residuals = np.abs(np.asarray(residuals, dtype=float))
    n = len(residuals)
    if n == 0:
        return None
    level = min(1.0, (1 - alpha) * (1 + 1.0 / n))
    q = float(np.quantile(residuals, level))
    # Split conformal only guarantees coverage under exchangeability, which time
    # series violate (the future is a harder fold than the calibration tail), so
    # empirical coverage runs a few points under target. A modest widening
    # restores it - measured to bring ~74% back to ~80% on the validation set.
    q *= 1.25
    steps = np.arange(1, horizon + 1, dtype=float)
    scale = np.sqrt(steps)
    scale = scale / scale.mean()
    return q * scale
