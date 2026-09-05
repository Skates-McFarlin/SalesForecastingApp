"""The closed loop - Phase 5.

The app grades its own past forecasts (the Phase 1 ledger records forecast +
realized actual per SKU). Here we turn that history into per-SKU CORRECTIONS:

- **bias**: if a product's sales consistently run above/below what we forecast,
  scale future forecasts to close that gap.
- **width**: if a product's realized errors land outside the forecast band more
  (or less) often than the band claims, widen (or tighten) it to hit its target
  coverage - so the safety stock derived from it is honestly sized.

Both are damped toward "no correction" by how few observations there are
(empirical-Bayes shrinkage) and clamped, so a couple of noisy cycles can't wildly
rescale a forecast. Applied in the forecast pipeline, so corrections propagate to
the reorder, the exceptions, and the budget plan. This is what makes the app get
measurably better at THIS business the longer it runs.
"""
import statistics
from collections import defaultdict

import numpy as np

from app.models.ledger_item import LedgerItem

MIN_BIAS_OBS = 2   # reconciled cycles before trusting a bias correction
MIN_WIDTH_OBS = 3  # more for interval calibration (needs a spread of errors)
BIAS_CLAMP = (0.6, 1.6)
WIDTH_CLAMP = (0.6, 1.8)


def _shrink(raw, n, k):
    """Pull a raw multiplier toward 1.0 when observations are few: with n=k the
    correction is halved, approaching the raw value as n grows."""
    return 1.0 + (raw - 1.0) * (n / (n + k))


def corrections_by_key():
    """{product_key: {bias, width, n, coverage}} learned from reconciled ledger
    items. A key appears only when it has enough history for at least one
    correction."""
    rows = LedgerItem.query.filter_by(reconciled=True).all()
    by_key = defaultdict(list)
    for it in rows:
        if it.actual is not None:
            by_key[it.product_key].append(it)

    out = {}
    for key, items in by_key.items():
        # Bias is measured against the RAW forecast (pre-correction) so it
        # converges to the true model bias, not its square root.
        ratios = []
        for it in items:
            base = it.raw_forecast if it.raw_forecast is not None else it.forecast
            if base and base > 0:
                ratios.append(it.actual / base)
        pairs = [
            ((it.forecast_high - it.forecast_low) / 2.0, abs(it.actual - it.forecast))
            for it in items
            if it.forecast_low is not None and it.forecast_high is not None
            and it.forecast_high > it.forecast_low
        ]
        within = [
            it for it in items
            if it.forecast_low is not None and it.forecast_high is not None
            and it.forecast_low <= it.actual <= it.forecast_high
        ]

        corr = {}
        if len(ratios) >= MIN_BIAS_OBS:
            b = _shrink(statistics.median(ratios), len(ratios), 2)
            corr["bias"] = round(min(BIAS_CLAMP[1], max(BIAS_CLAMP[0], b)), 3)
        if len(pairs) >= MIN_WIDTH_OBS:
            halfs = [p[0] for p in pairs]
            errs = [p[1] for p in pairs]
            avg_half = statistics.mean(halfs)
            if avg_half > 0:
                # Half-width that WOULD have covered ~80% of realized errors,
                # relative to the band we actually showed.
                w = _shrink(float(np.quantile(errs, 0.8)) / avg_half, len(pairs), 3)
                corr["width"] = round(min(WIDTH_CLAMP[1], max(WIDTH_CLAMP[0], w)), 3)

        if corr:
            corr["n"] = len(items)
            corr["coverage"] = round(len(within) / len(items), 3)
            out[key] = corr
    return out


def apply_correction(fc, corr):
    """Return a corrected Forecast: scale the point forecast by the learned bias
    and rescale the band around it by the learned width. Non-destructive."""
    from app.forecasting.base import Forecast, clip_nonneg

    if not corr:
        return fc
    bias = corr.get("bias", 1.0)
    width = corr.get("width", 1.0)
    yhat = np.asarray(fc.yhat, dtype=float)
    high = np.asarray(fc.high, dtype=float)
    low = np.asarray(fc.low, dtype=float)

    yhat_c = clip_nonneg(yhat * bias)
    up = np.maximum(0.0, (high - yhat)) * width
    dn = np.maximum(0.0, (yhat - low)) * width
    return Forecast(yhat=yhat_c, low=clip_nonneg(yhat_c - dn), high=yhat_c + up)


def learning_summary():
    """Catalog-wide view of the closed loop for the Track record tab: how many
    SKUs the app has learned corrections for, and the realized band coverage."""
    corr = corrections_by_key()
    reconciled = LedgerItem.query.filter_by(reconciled=True).count()
    biased = sum(1 for c in corr.values() if "bias" in c)
    calibrated = sum(1 for c in corr.values() if "width" in c)
    return {
        "reconciled_items": reconciled,
        "corrected_skus": len(corr),
        "bias_skus": biased,
        "width_skus": calibrated,
    }
