"""Intermittent-demand specialization (Phase 2).

Products with erratic on-and-off sales (many zero months, occasional bursts)
break smooth models like ETS/Theta - and even LightGBM smears the zeros. This
module (1) classifies a SKU's demand pattern from its history with the standard
Syntetos-Boylan cut and (2) forecasts the intermittent/lumpy ones with methods
built for that shape (Croston, TSB), which separate "how often does a sale
happen" from "how big is it when it does." Routing by a detected demand class
is principled and safe, unlike the per-SKU model *selection* that overfit in
Phase 1.
"""
import numpy as np
import pandas as pd
from statsforecast import StatsForecast
from statsforecast.models import CrostonOptimized, TSB

from .base import MONTHLY

# Syntetos-Boylan thresholds. ADI = average demand interval (periods per
# demand occurrence); CV2 = squared coefficient of variation of the non-zero
# demand sizes. ADI >= 1.32 means demand is spaced out enough that Croston/TSB
# beat smooth methods; CV2 >= 0.49 further splits "lumpy" from "intermittent".
ADI_CUT = 1.32
CV2_CUT = 0.49
INTERMITTENT_LABELS = {"intermittent", "lumpy"}


def demand_pattern(df_sku, grain=MONTHLY):
    """Classify a SKU: smooth | erratic | intermittent | lumpy | no-demand."""
    s = df_sku.sort_values("ds")
    y = s["y"].to_numpy(dtype=float)
    nz = y[y > 0]
    if len(nz) == 0:
        return "no-demand"
    span = len(pd.date_range(s["ds"].min(), s["ds"].max(), freq=grain.freq))
    adi = span / len(nz)
    mean_nz = nz.mean()
    cv2 = float((nz.std() / mean_nz) ** 2) if mean_nz > 0 else 0.0

    if adi >= ADI_CUT and cv2 >= CV2_CUT:
        return "lumpy"
    if adi >= ADI_CUT:
        return "intermittent"
    if cv2 >= CV2_CUT:
        return "erratic"
    return "smooth"


def forecast_all(df_all, group_col, horizon, grain=MONTHLY):
    """Point forecasts for the given (intermittent) series: the mean of Croston
    and TSB. These methods return a low constant per-period rate; StatsForecast
    won't give them model-based intervals (that arrives with conformal in a
    later phase), so the caller derives the band from series variability.
    Returns {group_key: point_yhat_array}."""
    if df_all.empty:
        return {}
    sf_df = (
        df_all.rename(columns={group_col: "unique_id"})[["unique_id", "ds", "y"]]
        .sort_values(["unique_id", "ds"])
    )
    engine = StatsForecast(
        models=[CrostonOptimized(), TSB(alpha_d=0.2, alpha_p=0.2)],
        freq=grain.freq,
        n_jobs=1,
    )
    fc = engine.forecast(df=sf_df, h=horizon)
    if "unique_id" not in fc.columns:
        fc = fc.reset_index()

    out = {}
    for uid, g in fc.groupby("unique_id"):
        g = g.sort_values("ds")
        croston = g["CrostonOptimized"].to_numpy()[:horizon]
        tsb = g["TSB"].to_numpy()[:horizon]
        out[uid] = np.clip(np.mean([croston, tsb], axis=0), a_min=0.0, a_max=None)
    return out
