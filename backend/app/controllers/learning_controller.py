"""Self-grading track record (formerly the "closed loop").

The Phase 1 ledger records each forecast plus the realized actual once its
window closes. This module turns that history into an honest, per-SKU **track
record**: how far the app's forecasts have actually run high or low (observed
bias) and how often reality landed inside the stated band (realized coverage).

It deliberately does **not** auto-rescale future forecasts. An earlier version
did (learned a bias multiplier and a band-width multiplier and applied them),
and it looked great on a synthetic simulator that injected a *persistent* bias.
Measured on real M5 retail demand across a multi-cycle walk-forward, that
auto-correction was net-negative on every demand class: the learned bias is
mostly cycle-to-cycle noise (applying it added ~6-10% MASE), and the width
rescale fought the already-calibrated conformal band (coverage 82% -> 68-73%).
So the ledger earns its keep as accountability and transparency - a forecaster
you can check - not as a self-tuning knob that quietly makes things worse.
"""
from collections import defaultdict

import numpy as np

from app.models.ledger_item import LedgerItem

MIN_GRADE_OBS = 2      # reconciled cycles before a SKU gets a track record
BIAS_FLAG_THRESHOLD = 0.15  # |observed bias - 1| beyond this = "runs consistently high/low"


def observed_by_key():
    """{product_key: {bias, coverage, n}} - OBSERVED diagnostics from reconciled
    ledger items (not corrections applied to anything). `bias` is the median
    ratio of actual to what we forecast (>1 = we under-forecast); `coverage` is
    the fraction of cycles that landed inside the stated band."""
    rows = LedgerItem.query.filter_by(reconciled=True).all()
    by_key = defaultdict(list)
    for it in rows:
        if it.actual is not None:
            by_key[it.product_key].append(it)

    out = {}
    for key, items in by_key.items():
        if len(items) < MIN_GRADE_OBS:
            continue
        ratios = []
        for it in items:
            base = it.raw_forecast if it.raw_forecast is not None else it.forecast
            if base and base > 0:
                ratios.append(it.actual / base)
        within = [
            it for it in items
            if it.forecast_low is not None and it.forecast_high is not None
            and it.forecast_low <= it.actual <= it.forecast_high
        ]
        rec = {"n": len(items), "coverage": round(len(within) / len(items), 3)}
        if ratios:
            rec["bias"] = round(float(np.median(ratios)), 3)
        out[key] = rec
    return out


def learning_summary():
    """Catalog-wide self-grading view for the Track record tab: how many
    forecasts have been graded, how many SKUs run consistently high or low, and
    the realized band coverage overall."""
    obs = observed_by_key()
    reconciled = LedgerItem.query.filter_by(reconciled=True).count()
    banded = LedgerItem.query.filter(
        LedgerItem.reconciled.is_(True),
        LedgerItem.forecast_low.isnot(None),
        LedgerItem.forecast_high.isnot(None),
    ).all()
    covered = sum(
        1 for it in banded
        if it.actual is not None and it.forecast_low <= it.actual <= it.forecast_high
    )
    biased = sum(
        1 for c in obs.values()
        if "bias" in c and abs(c["bias"] - 1.0) >= BIAS_FLAG_THRESHOLD
    )
    return {
        "reconciled_items": reconciled,
        "graded_skus": len(obs),
        "biased_skus": biased,
        "coverage": round(covered / len(banded), 3) if banded else None,
    }
