"""StatsForecast candidates - the fast statistical workhorses.

Nixtla StatsForecast fits a whole panel of series in one batched C++ call
(no per-series Python loop, no cmdstan subprocess), ~500x faster than Prophet
and typically as accurate or better on monthly data. One call yields several
models at once (AutoETS, an optimized Theta, and seasonal-naive) with
prediction intervals, so the statistical half of the competition is a single
cheap pass. n_jobs=1 deliberately: StatsForecast's parallelism uses
multiprocessing, which is a trap inside a frozen Windows exe - the C++ core is
fast enough single-process (all 498 real SKUs in ~12s).
"""
import numpy as np
import pandas as pd
from statsforecast import StatsForecast
from statsforecast.models import AutoETS, DynamicOptimizedTheta, SeasonalNaive

from .base import Forecast, clip_nonneg, MONTHLY

LEVEL = 80  # interval coverage StatsForecast is asked for

# Column name each model writes in the forecast frame -> our model id.
MODEL_COLUMNS = {
    "AutoETS": "ets",
    "DynamicOptimizedTheta": "theta",
    "SeasonalNaive": "seasonal-naive",
}


def _new_engine(grain):
    season = grain.season_length
    return StatsForecast(
        models=[
            AutoETS(season_length=season),
            DynamicOptimizedTheta(season_length=season),
            SeasonalNaive(season_length=season),
        ],
        freq=grain.freq,
        n_jobs=1,
        # Any series a model chokes on (too short, degenerate) falls back
        # gracefully instead of failing the whole batch.
        fallback_model=SeasonalNaive(season_length=season),
    )


def forecast_all(df_all, group_col, horizon, grain=MONTHLY):
    """Batched forecast for every series. Returns
    {model_id: {group_key: Forecast}} covering the `horizon` periods after each
    series' last observation."""
    sf_df = (
        df_all.rename(columns={group_col: "unique_id"})[["unique_id", "ds", "y"]]
        .sort_values(["unique_id", "ds"])
    )
    fc = _new_engine(grain).forecast(df=sf_df, h=horizon, level=[LEVEL])
    if "unique_id" not in fc.columns:
        fc = fc.reset_index()

    out = {col_id: {} for col_id in MODEL_COLUMNS.values()}
    for uid, g in fc.groupby("unique_id"):
        g = g.sort_values("ds")
        for col, model_id in MODEL_COLUMNS.items():
            yhat = clip_nonneg(g[col].to_numpy()[:horizon])
            lo_col, hi_col = f"{col}-lo-{LEVEL}", f"{col}-hi-{LEVEL}"
            low = clip_nonneg(g[lo_col].to_numpy()[:horizon]) if lo_col in g else yhat
            high = clip_nonneg(g[hi_col].to_numpy()[:horizon]) if hi_col in g else yhat
            out[model_id][uid] = Forecast(yhat=yhat, low=low, high=high)
    return out
