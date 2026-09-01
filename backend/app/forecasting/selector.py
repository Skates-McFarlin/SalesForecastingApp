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

from . import statistical, borrowed_shape, intermittent
from .base import Forecast, clip_nonneg
from .lightgbm_model import LightGBMForecaster

# A SKU below (horizon + this) months can't learn its own yearly shape; it uses
# the borrowed-shape cold-start path instead of the ensemble.
MIN_TRAIN_MONTHS = 12
ENSEMBLE = ["ets", "theta", "lightgbm"]  # strong models only; naive excluded
ENSEMBLE_NAME = "ensemble"
THIN = "seasonal-borrowed"
INTERMITTENT_NAME = "intermittent"


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

    # Detect intermittent/lumpy demand among mature SKUs and forecast those with
    # Croston/TSB instead of the smooth ensemble (they'd smear the zeros).
    intermittent_skus = []
    for g in products:
        if history_months_by_group.get(g, 0) >= horizon + MIN_TRAIN_MONTHS:
            if intermittent.demand_pattern(df_all[df_all[group_col] == g]) in intermittent.INTERMITTENT_LABELS:
                intermittent_skus.append(g)
    interm_full = intermittent.forecast_all(
        df_all[df_all[group_col].isin(intermittent_skus)], group_col, horizon
    ) if intermittent_skus else {}

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

        members = [m for m in (member(mid, g) for mid in ENSEMBLE) if m is not None]
        label = ENSEMBLE_NAME

        # Intermittent/lumpy: ADD the Croston/TSB specialist to the ensemble
        # rather than replacing it - so the intermittent-appropriate rate
        # contributes without discarding any seasonal/trend signal the other
        # models capture (a "sells only in December" product must keep its
        # seasonality). Combining, not selecting - the Phase 1 lesson.
        if interm_full.get(g) is not None:
            pt = clip_nonneg(interm_full[g])
            std = float(df_all[df_all[group_col] == g]["y"].std(ddof=0)) or 1.0
            half = 1.28 * std  # ~80% band from the SKU's own variability
            members.append(Forecast(yhat=pt, low=clip_nonneg(pt - half), high=pt + half))
            label = INTERMITTENT_NAME

        if not members:
            df_sku = df_all[df_all[group_col] == g]
            results[g] = (THIN, borrowed_shape.forecast(df_sku, forecast_start_date, horizon))
            continue

        yhat = clip_nonneg(np.mean([m.yhat for m in members], axis=0))
        low = clip_nonneg(np.mean([m.low for m in members], axis=0))
        high = clip_nonneg(np.mean([m.high for m in members], axis=0))
        results[g] = (label, Forecast(yhat=yhat, low=low, high=high))

    return results
