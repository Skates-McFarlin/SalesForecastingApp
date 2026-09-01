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

LAGS = [1, 2, 3, 6, 12]
FEATURES = [f"lag_{L}" for L in LAGS] + [
    "rmean_3", "rmean_6", "rstd_3", "month", "quarter", "cat", "hist_len",
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


def _features_at(vals, months, cat_code, hist_len, i):
    row = []
    for L in LAGS:
        row.append(vals[i - L] if i - L >= 0 else np.nan)
    seg3, seg6 = vals[max(0, i - 3):i], vals[max(0, i - 6):i]
    row.append(np.mean(seg3) if len(seg3) else np.nan)
    row.append(np.mean(seg6) if len(seg6) else np.nan)
    row.append(np.std(seg3) if len(seg3) > 1 else np.nan)
    row.append(months[i])
    row.append((months[i] - 1) // 3 + 1)
    row.append(cat_code)
    row.append(hist_len)
    return row


class LightGBMForecaster:
    name = NAME

    def forecast_all(self, df_all, group_col, products, start_date, horizon,
                     category_by_group, history_months_by_group):
        """Train the global model on every SKU's history, then produce a
        recursive forecast per SKU. Returns {group_key: Forecast}."""
        cats = sorted({(category_by_group.get(g) or "unknown") for g in products})
        cat_code = {c: i for i, c in enumerate(cats)}

        series = {}          # group_key -> (vals, months)
        X, y = [], []
        for g in products:
            vals, months = _continuous_series(df_all[df_all[group_col] == g])
            series[g] = (vals, months)
            code = cat_code.get(category_by_group.get(g) or "unknown", -1)
            hist_len = history_months_by_group.get(g, len(vals))
            for i in range(1, len(vals)):  # need at least lag_1
                X.append(_features_at(vals, months, code, hist_len, i))
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
            for k in range(horizon):
                ext_months.append(int(future_months[k]))
                i = len(ext_vals)  # position of the month we're predicting
                feat = _features_at(np.array(ext_vals + [0.0]), np.array(ext_months), code, hist_len, i)
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
