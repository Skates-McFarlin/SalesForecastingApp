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

from .base import Forecast, future_index, clip_nonneg

NAME = "lightgbm"

# Richer than the original lag set: a 24-month (2-year) seasonal lag, annual
# rolling stats, a recent-trend slope, cyclical month encoding, and a
# category-relative size feature so a SKU inherits some of its category's
# intelligence (helps thin SKUs most). Trees don't need the cyclical encoding
# strictly, but it's cheap and lets a split treat Dec/Jan as adjacent.
LAGS = [1, 2, 3, 6, 12, 24]
FEATURES = [f"lag_{L}" for L in LAGS] + [
    "rmean_3", "rmean_6", "rmean_12", "rstd_3", "rstd_6", "trend6",
    "month_sin", "month_cos", "cat", "hist_len", "cat_rel",
]


def _continuous_series(df_sku):
    """A gap-free monthly (values, calendar-month) pair for one SKU; months the
    file skipped are treated as zero sales so lags line up correctly."""
    s = df_sku.sort_values("ds")
    idx = pd.date_range(s["ds"].min(), s["ds"].max(), freq="MS")
    by_month = {d.strftime("%Y-%m"): float(v) for d, v in zip(s["ds"], s["y"])}
    vals = np.array([by_month.get(d.strftime("%Y-%m"), 0.0) for d in idx])
    months = np.array([d.month for d in idx])
    return vals, months


def _features_at(vals, months, cat_code, hist_len, cat_rel, i):
    row = []
    for L in LAGS:
        row.append(vals[i - L] if i - L >= 0 else np.nan)
    seg3, seg6, seg12 = vals[max(0, i - 3):i], vals[max(0, i - 6):i], vals[max(0, i - 12):i]
    row.append(np.mean(seg3) if len(seg3) else np.nan)
    row.append(np.mean(seg6) if len(seg6) else np.nan)
    row.append(np.mean(seg12) if len(seg12) else np.nan)
    row.append(np.std(seg3) if len(seg3) > 1 else np.nan)
    row.append(np.std(seg6) if len(seg6) > 1 else np.nan)
    # Recent trend: slope of the last up-to-6 months.
    row.append(np.polyfit(np.arange(len(seg6)), seg6, 1)[0] if len(seg6) > 1 else 0.0)
    m = months[i]
    row.append(np.sin(2 * np.pi * m / 12))
    row.append(np.cos(2 * np.pi * m / 12))
    row.append(cat_code)
    row.append(hist_len)
    row.append(cat_rel)
    return row


class LightGBMForecaster:
    name = NAME

    def forecast_all(self, df_all, group_col, products, start_date, horizon,
                     category_by_group, history_months_by_group):
        """Train the global model on every SKU's history, then produce a
        recursive forecast per SKU. Returns {group_key: Forecast}."""
        cats = sorted({(category_by_group.get(g) or "unknown") for g in products})
        cat_code = {c: i for i, c in enumerate(cats)}

        # Build every SKU's continuous series first, then derive a category-
        # relative size: how big this SKU runs versus the average SKU in its
        # category. Lets the model place a thin SKU within its category.
        series = {g: _continuous_series(df_all[df_all[group_col] == g]) for g in products}
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
            vals, months = series[g]
            code = cat_code.get(category_by_group.get(g) or "unknown", -1)
            hist_len = history_months_by_group.get(g, len(vals))
            for i in range(1, len(vals)):  # need at least lag_1
                X.append(_features_at(vals, months, code, hist_len, cat_rel[g], i))
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

        future_months = np.array([d.month for d in future_index(start_date, horizon)])

        out = {}
        for g in products:
            vals, months = series[g]
            code = cat_code.get(category_by_group.get(g) or "unknown", -1)
            hist_len = history_months_by_group.get(g, len(vals))
            ext_vals = list(vals)
            ext_months = list(months)
            preds = []
            crel = cat_rel[g]
            for k in range(horizon):
                ext_months.append(int(future_months[k]))
                i = len(ext_vals)  # position of the month we're predicting
                feat = _features_at(np.array(ext_vals + [0.0]), np.array(ext_months), code, hist_len, crel, i)
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
