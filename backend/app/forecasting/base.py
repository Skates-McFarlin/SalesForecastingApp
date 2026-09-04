"""Shared types and helpers for the forecaster competition."""
from dataclasses import dataclass
from typing import NamedTuple

import numpy as np
import pandas as pd
from scipy.stats import norm

DEFAULT_INTERVAL_WIDTH = 0.8


@dataclass(frozen=True)
class Grain:
    """The time grain the whole engine runs at, so weekly is a config rather
    than a rewrite. Monthly stays the default; weekly is the operational grain
    for inventory (see the roadmap)."""
    label: str            # "monthly" | "weekly"
    freq: str             # pandas offset alias for the period start
    season_length: int    # periods per year (12 or 52)
    lags: tuple           # LightGBM autoregressive lags, in periods
    roll_windows: tuple   # rolling mean/std windows (short, mid, long), in periods
    min_train: int        # below (horizon + this) periods a SKU uses cold-start
    sufficient_history: int  # enough periods to trust a SKU's own seasonality

    def future_index(self, start, horizon):
        return pd.date_range(start=start, periods=horizon, freq=self.freq)

    def period_key(self, ts):
        """Stable key for matching a timestamp to a period (align data<->forecast)."""
        ts = pd.Timestamp(ts)
        return ts.strftime("%Y-%m") if self.label == "monthly" else ts.strftime("%Y-%m-%d")

    def period_of_year(self, ts):
        """1..12 for monthly, ISO week 1..53 for weekly - the seasonal bucket."""
        ts = pd.Timestamp(ts)
        return ts.month if self.label == "monthly" else int(ts.isocalendar().week)


MONTHLY = Grain(
    label="monthly", freq="MS", season_length=12,
    lags=(1, 2, 3, 6, 12, 24), roll_windows=(3, 6, 12),
    min_train=12, sufficient_history=24,
)
WEEKLY = Grain(
    label="weekly", freq="W-SUN", season_length=52,
    lags=(1, 2, 3, 4, 8, 52), roll_windows=(4, 8, 26),
    min_train=26, sufficient_history=52,
)


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


def future_index(start_date, horizon, freq="MS"):
    """The horizon's period-start timestamps at the given frequency (month-start
    by default; pass a Grain's freq for weekly)."""
    return pd.date_range(start=start_date, periods=horizon, freq=freq)


# Assumed correlation between a SKU's month-to-month forecast errors. Pure
# quadrature (rho=0) treats the 12 months as independent, which badly
# understates the band on an ANNUAL total: a real forecast that's off is usually
# off the same direction all year (a level/trend/seasonality miss persists), not
# independently each month. Measured on a proper out-of-sample backtest (train
# on history, score the truly-unseen next year), the per-month bands were a
# well-calibrated ~80% but rho=0 covered only ~46% of the annual total; a modest
# rho lands the well-forecast SKUs back near their stated ~80% (0.3 -> ensemble
# ~83%) without inflating the band the way rho=1 (linear sum) would. This is the
# knob that makes a service-level order honest. Var(sum) = rho*(sum sigma)^2 +
# (1-rho)*sum(sigma^2), interpolating linear sum (rho=1) and quadrature (rho=0).
ERROR_CORRELATION = 0.3


def aggregate_interval(forecast: Forecast, interval_width=DEFAULT_INTERVAL_WIDTH):
    """Confidence band for the SUMMED forecast. Combines the monthly spreads
    accounting for cross-month error correlation (see ERROR_CORRELATION) - pure
    quadrature assumes independent months and makes the annual band far too
    narrow; a plain linear sum assumes every month misses together and makes it
    too wide. The truth is in between."""
    total = forecast.total
    try:
        z = norm.ppf(0.5 + interval_width / 2)
        sigmas = (np.asarray(forecast.high) - np.asarray(forecast.low)) / (2 * z)
        rho = ERROR_CORRELATION
        var = rho * float(np.sum(sigmas)) ** 2 + (1 - rho) * float(np.sum(sigmas ** 2))
        spread = z * float(np.sqrt(var))
    except Exception:  # noqa: BLE001 - fall back to the raw summed bounds
        return float(np.sum(forecast.low)), float(np.sum(forecast.high))
    return max(0.0, total - spread), total + spread


def mae(pred, actual):
    pred = np.asarray(pred, dtype=float)
    actual = np.asarray(actual, dtype=float)
    return float(np.mean(np.abs(pred - actual)))


def period_actuals(df_history, start_date, horizon, grain=MONTHLY):
    """Actual y for each period of a window, 0 where there's no row - used to
    score a backtest against what really happened, at any grain."""
    by_period = {
        grain.period_key(d): float(v)
        for d, v in zip(df_history["ds"], df_history["y"])
    }
    wanted = [grain.period_key(d) for d in grain.future_index(start_date, horizon)]
    return np.array([by_period.get(k, 0.0) for k in wanted])


def monthly_actuals(df_history, start_date, horizon):
    """Back-compat monthly wrapper for period_actuals."""
    return period_actuals(df_history, start_date, horizon, MONTHLY)


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
