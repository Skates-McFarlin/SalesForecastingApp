"""Global LightGBM forecaster - one gradient-boosted model across all SKUs.

This is the M4/M5-winning shape: pool every SKU into a single model with lag,
rolling, and calendar features so products learn from each other, then predict
each series recursively over the horizon. One model serves the whole catalog,
so it's trained once (fast) rather than per SKU. Point forecast comes from
LightGBM; the interval is scaled from each SKU's own historical volatility,
widening with the horizon.
"""
import numpy as np
import pandas as pd
import lightgbm as lgb

from .base import Forecast, clip_nonneg, MONTHLY

NAME = "lightgbm"

# Feature set (grain-parameterized): autoregressive lags including a full-year
# seasonal lag, rolling mean/std over short/mid/long windows, a recent-trend
# slope, a cyclical seasonal-position encoding, and a category-relative size
# feature so a SKU inherits some of its category's intelligence (helps thin SKUs
# most). Trees don't strictly need the cyclical encoding, but it's cheap and
# lets a split treat the year's ends as adjacent.


def _continuous_series(df_sku, grain):
    """A gap-free (values, period-of-year) pair for one SKU at the grain;
    periods the data skipped are treated as zero sales so lags line up."""
    s = df_sku.sort_values("ds")
    idx = pd.date_range(s["ds"].min(), s["ds"].max(), freq=grain.freq)
    by_period = {grain.period_key(d): float(v) for d, v in zip(s["ds"], s["y"])}
    vals = np.array([by_period.get(grain.period_key(d), 0.0) for d in idx])
    poy = np.array([grain.period_of_year(d) for d in idx])
    return vals, poy


def _features_at(vals, poy, cat_code, hist_len, cat_rel, i, grain):
    ws, wm, wl = grain.roll_windows
    row = []
    for L in grain.lags:
        row.append(vals[i - L] if i - L >= 0 else np.nan)
    seg_s, seg_m, seg_l = vals[max(0, i - ws):i], vals[max(0, i - wm):i], vals[max(0, i - wl):i]
    row.append(np.mean(seg_s) if len(seg_s) else np.nan)
    row.append(np.mean(seg_m) if len(seg_m) else np.nan)
    row.append(np.mean(seg_l) if len(seg_l) else np.nan)
    row.append(np.std(seg_s) if len(seg_s) > 1 else np.nan)
    row.append(np.std(seg_m) if len(seg_m) > 1 else np.nan)
    # Recent trend: slope of the last up-to-`wm` periods.
    row.append(np.polyfit(np.arange(len(seg_m)), seg_m, 1)[0] if len(seg_m) > 1 else 0.0)
    p = poy[i]
    row.append(np.sin(2 * np.pi * p / grain.season_length))
    row.append(np.cos(2 * np.pi * p / grain.season_length))
    row.append(cat_code)
    row.append(hist_len)
    row.append(cat_rel)
    return row


class LightGBMForecaster:
    name = NAME

    def forecast_all(self, df_all, group_col, products, start_date, horizon,
                     category_by_group, history_months_by_group, grain=MONTHLY):
        """Train the global model on every SKU's history, then produce a
        recursive forecast per SKU. Returns {group_key: Forecast}."""
        cats = sorted({(category_by_group.get(g) or "unknown") for g in products})
        cat_code = {c: i for i, c in enumerate(cats)}

        # Build every SKU's continuous series first, then derive a category-
        # relative size: how big this SKU runs versus the average SKU in its
        # category. Lets the model place a thin SKU within its category.
        series = {g: _continuous_series(df_all[df_all[group_col] == g], grain) for g in products}
        sku_mean = {g: float(np.mean(series[g][0])) if len(series[g][0]) else 0.0 for g in products}
        cat_means = {}
        for c in cats:
            vals_in_cat = [sku_mean[g] for g in products if (category_by_group.get(g) or "unknown") == c]
            cat_means[c] = float(np.mean(vals_in_cat)) if vals_in_cat else 0.0
        cat_rel = {
            g: (sku_mean[g] / cat_means[category_by_group.get(g) or "unknown"])
            if cat_means.get(category_by_group.get(g) or "unknown", 0) > 0 else 1.0
            for g in products
        }

        X, y = [], []
        for g in products:
            vals, poy = series[g]
            code = cat_code.get(category_by_group.get(g) or "unknown", -1)
            hist_len = history_months_by_group.get(g, len(vals))
            for i in range(1, len(vals)):  # need at least lag_1
                X.append(_features_at(vals, poy, code, hist_len, cat_rel[g], i, grain))
                y.append(vals[i])

        if not X:
            return {g: None for g in products}

        model = lgb.LGBMRegressor(
            n_estimators=300,
            learning_rate=0.05,
            num_leaves=31,
            min_child_samples=20,
            subsample=0.8,
            colsample_bytree=0.8,
            verbosity=-1,
        )
        model.fit(np.array(X, dtype=float), np.array(y, dtype=float))

        future_poy = np.array([grain.period_of_year(d) for d in grain.future_index(start_date, horizon)])

        out = {}
        for g in products:
            vals, poy = series[g]
            code = cat_code.get(category_by_group.get(g) or "unknown", -1)
            hist_len = history_months_by_group.get(g, len(vals))
            ext_vals = list(vals)
            ext_poy = list(poy)
            preds = []
            crel = cat_rel[g]
            for k in range(horizon):
                ext_poy.append(int(future_poy[k]))
                i = len(ext_vals)  # position of the period we're predicting
                feat = _features_at(np.array(ext_vals + [0.0]), np.array(ext_poy), code, hist_len, crel, i, grain)
                p = float(model.predict(np.array([feat], dtype=float))[0])
                p = max(0.0, p)
                ext_vals.append(p)
                preds.append(p)
            yhat = clip_nonneg(preds)

            std = float(np.std(vals)) if len(vals) > 1 else max(1.0, float(np.mean(vals)))
            steps = np.arange(1, horizon + 1)
            spread = std * np.sqrt(steps)
            out[g] = Forecast(yhat=yhat, low=clip_nonneg(yhat - 1.28 * spread), high=yhat + 1.28 * spread)
        return out
