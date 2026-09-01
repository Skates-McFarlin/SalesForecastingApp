"""Ensemble forecaster (batched, Prophet-free).

Every candidate forecasts the whole catalog in one batched call, then mature
SKUs get the simple mean of the strong models (ETS + Theta + global LightGBM).
Combining beats selecting: picking a per-SKU "winner" on one holdout overfits
and measured WORSE than any single strong model (5.58 vs ~5.31 MAE on the real
file), while the equal-weight ensemble ties the best model and is far more
robust across datasets - the classic forecast-combination result. Seasonal-
naive is computed (a useful floor / accuracy-tab baseline) but kept OUT of the
blend since it's the weak member. Thin SKUs skip the ensemble and use the
borrowed-shape cold-start path.
"""
import numpy as np

from . import statistical, borrowed_shape
from .base import Forecast, clip_nonneg
from .lightgbm_model import LightGBMForecaster

# A SKU below (horizon + this) months can't learn its own yearly shape; it uses
# the borrowed-shape cold-start path instead of the ensemble.
MIN_TRAIN_MONTHS = 12
ENSEMBLE = ["ets", "theta", "lightgbm"]  # strong models only; naive excluded
ENSEMBLE_NAME = "ensemble"
THIN = "seasonal-borrowed"


def run_forecast(
    df_all, group_col, products, forecast_start_date, horizon,
    category_by_group, history_months_by_group, seasonal_index_by_group,
):
    """Returns {group_key: (model_label, Forecast)}."""
    stat_full = statistical.forecast_all(df_all, group_col, horizon)
    lgbm_full = LightGBMForecaster().forecast_all(
        df_all, group_col, products, forecast_start_date, horizon,
        category_by_group, history_months_by_group,
    )

    def member(mid, g):
        return lgbm_full.get(g) if mid == "lightgbm" else stat_full.get(mid, {}).get(g)

    results = {}
    for g in products:
        n = history_months_by_group.get(g, 0)
        if n < horizon + MIN_TRAIN_MONTHS:
            df_sku = df_all[df_all[group_col] == g]
            results[g] = (THIN, borrowed_shape.forecast(
                df_sku, forecast_start_date, horizon, seasonal_index_by_group.get(g)))
            continue

        members = [member(mid, g) for mid in ENSEMBLE]
        members = [m for m in members if m is not None]
        if not members:
            df_sku = df_all[df_all[group_col] == g]
            results[g] = (THIN, borrowed_shape.forecast(df_sku, forecast_start_date, horizon))
            continue

        yhat = clip_nonneg(np.mean([m.yhat for m in members], axis=0))
        low = clip_nonneg(np.mean([m.low for m in members], axis=0))
        high = clip_nonneg(np.mean([m.high for m in members], axis=0))
        results[g] = (ENSEMBLE_NAME, Forecast(yhat=yhat, low=low, high=high))

    return results
