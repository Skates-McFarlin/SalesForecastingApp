"""Cold-start forecaster for thin SKUs, with no Prophet dependency.

A new/thin SKU can't learn its own yearly shape, so we take a robust recent
level from what little history it has and redistribute it across the horizon by
a borrowed monthly seasonal index (from its category, or a seasonal prior).
The interval is floored to reflect how little we actually know - the least
certain forecasts must not look the most certain (the 360-360 problem).
"""
import numpy as np

from .base import Forecast, future_index, clip_nonneg


def thin_history_interval_floor(n_months):
    """Minimum relative half-width, shrinking ~1/sqrt(history): a 4-month SKU
    gets ~+/-50%, an 18-month one ~+/-24%."""
    return min(0.6, 1.0 / (max(1, n_months) ** 0.5))


def forecast(df_history, start_date, horizon, seasonal_index=None):
    hist = df_history.sort_values("ds")
    y = hist["y"].to_numpy(dtype=float)
    n = len(y)
    # Robust recent level: mean of the last up-to-12 months.
    level = float(np.mean(y[-12:])) if n else 0.0

    months = np.array([d.month for d in future_index(start_date, horizon)])
    if seasonal_index:
        mult = np.array([seasonal_index.get(int(m), 1.0) for m in months])
    else:
        mult = np.ones(horizon)
    yhat = clip_nonneg(level * mult)

    total = float(np.sum(yhat))
    floor = thin_history_interval_floor(n)
    # Per-month band that sums (in quadrature) to at least the floor fraction
    # of the total; distributed proportionally to each month's share.
    share = yhat / total if total > 0 else np.full(horizon, 1.0 / horizon)
    half = floor * total * share
    low = clip_nonneg(yhat - half)
    high = yhat + half
    return Forecast(yhat=yhat, low=low, high=high)
