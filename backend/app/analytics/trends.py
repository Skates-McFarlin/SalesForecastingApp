"""Trend & momentum intelligence.

Deterministic analytics over the catalog's sales history: for every SKU and
category, how demand is growing or shrinking, whether it's accelerating, and how
long a drift has run. This is the first "intelligence layer" primitive - the
assistant NARRATES and prioritizes these signals but never computes them, so the
numbers are always correct.

Momentum is measured **year-over-year** (a window vs the same window one year
ago), NOT vs the immediately preceding window. That matters: on seasonal demand,
"last 3 months vs the prior 3 months" mistakes every autumn for growth. Comparing
to the same calendar window a year earlier is seasonality-neutral, so a positive
number is real trend, not the season turning.
"""
import numpy as np
import pandas as pd


# Robustness thresholds. A momentum number is only worth narrating if it clears
# noise: the trend fit must explain the series (R^2) and be materially large; a
# YoY ratio needs a real denominator; a streak step must beat a wiggle. Without
# these, scanning many SKUs surfaces confident-sounding movers in pure noise.
MIN_BASE = 3.0          # min year-ago window units before a YoY ratio is trusted
TREND_R2 = 0.60         # rolling-annual-sum fit must explain this much variance
TREND_MIN = 0.03        # ...and be at least +/-3%/yr to count as a real trend
STREAK_GATE = 0.05      # a YoY step must exceed 5% of the series' level to count


def _season(grain_label):
    return 52 if grain_label == "weekly" else 12


def _yoy_growth(y, n, season):
    """Growth of the last `n` periods vs the `n` periods ending one year earlier.
    None without a full year-plus-`n` of history, or when the year-ago base is too
    small to divide by (near-zero denominators otherwise explode into fake %)."""
    if len(y) < season + n:
        return None
    recent = y[-n:].sum()
    prior = y[-(season + n):-season].sum()
    if prior < MIN_BASE:
        return None
    return round(float(recent / prior - 1.0), 4)


def _trend(y, season):
    """(trend_yr, significant): sustained annual trend as a fractional rate/year,
    seasonality-free, plus whether it's real rather than noise. We take the slope
    of the TRAILING ANNUAL SUM (a rolling `season`-period sum, which cancels
    seasonality) normalized by the average level. Significance is the fit's R^2
    (does a line actually describe the series?) AND a minimum magnitude - R^2 is
    robust to the rolling sum's autocorrelation, which would inflate a t-stat."""
    if len(y) < 2 * season:
        return None, False
    roll = np.convolve(y, np.ones(season), "valid")  # trailing annual sum
    n = len(roll)
    base = float(roll.mean())
    if n < 3 or base <= 0:
        return None, False
    x = np.arange(n)
    slope, intercept = np.polyfit(x, roll, 1)
    resid = roll - (slope * x + intercept)
    ss_tot = float(((roll - base) ** 2).sum())
    r2 = 1.0 - float((resid ** 2).sum()) / ss_tot if ss_tot > 0 else 0.0
    trend_yr = round(float(slope) * season / base, 4)
    return trend_yr, bool(r2 >= TREND_R2 and abs(trend_yr) >= TREND_MIN)


def _yoy_streak(y, season):
    """Signed count of consecutive most-recent periods whose year-over-year change
    keeps the same sign AND exceeds a 5%-of-(year-ago-level) wiggle. The gate is
    relative to the LOCAL year-ago base, not the series mean, so it works equally
    on a shrinking series (whose late absolute changes are small). Descriptive
    only ('down 6 periods') - whether it's worth surfacing is `drift_sig`."""
    if len(y) <= season:
        return 0
    diffs = y[season:] - y[:-season]      # aligned YoY deltas, oldest..newest
    base = y[:-season]
    gate = STREAK_GATE * np.maximum(base, 1.0)
    if len(diffs) == 0 or abs(diffs[-1]) <= gate[-1]:
        return 0
    sign = 1.0 if diffs[-1] > 0 else -1.0
    k = 0
    for i in range(len(diffs) - 1, -1, -1):
        if abs(diffs[i]) > gate[i] and ((diffs[i] > 0) == (sign > 0)):
            k += 1
        else:
            break
    return int(sign * k)


def _drift_sig(y, season):
    """Is there a real sustained drift? A t-test on the recent year-over-year
    RELATIVE changes (period vs a year ago, as a fraction): a genuine drift has a
    consistent non-zero mean; noise averages to ~0. Relative (not absolute) so it
    reads a shrinking series correctly, where late absolute deltas are tiny. This
    - not raw streak length - is the noise guard (random signs make 3-runs ~25% of
    the time, but rarely a significant mean)."""
    if len(y) <= season:
        return False
    base = y[:-season]; recent = y[season:]
    mask = base >= MIN_BASE                        # skip near-zero denominators
    r = recent[mask] / base[mask] - 1.0            # relative YoY change per period
    rr = r[-season:] if len(r) >= season else r    # the last ~year of them
    if len(rr) < 3:
        return False
    m = float(np.mean(rr)); s = float(np.std(rr, ddof=1))
    if s == 0:
        return m != 0
    t = m / (s / (len(rr) ** 0.5))
    return abs(t) >= 2.5


def series_momentum(y, season):
    """Momentum record for one demand series (chronological), with significance
    flags so the caller can refuse to narrate noise."""
    y = np.asarray(y, dtype=float)
    g3, g12 = _yoy_growth(y, 3, season), _yoy_growth(y, 12, season)
    accel = round(g3 - g12, 4) if (g3 is not None and g12 is not None) else None
    trend_yr, trend_sig = _trend(y, season)
    mean = float(y.mean())
    cv = float(y.std() / mean) if mean > 0 else 0.0
    # A single 12-vs-12 ratio averages out much per-period noise; it's real signal
    # only when it clears that residual noise (~sqrt(2)*cv/sqrt(season)).
    noise_g12 = (2 ** 0.5) * cv / (season ** 0.5)
    g12_sig = g12 is not None and abs(g12) >= 2 * noise_g12
    streak = _yoy_streak(y, season)
    drift_sig = _drift_sig(y, season)
    return {
        "trend_yr": trend_yr, "trend_sig": trend_sig,   # sustained direction + is-it-real
        "g3": g3, "g6": _yoy_growth(y, 6, season),
        "g12": g12, "g12_sig": bool(g12_sig),           # annual YoY + is-it-real
        "accel": accel,                                 # recent pace vs annual pace
        "streak": streak, "drift_sig": bool(drift_sig), # consecutive YoY periods + is-the-drift-real
        "recent_units": round(float(y[-season:].sum()) if len(y) >= season else float(y.sum()), 1),
        "cv": round(cv, 3), "n_periods": int(len(y)),
        # Worth a comment only if a real sustained trend OR a significant drift.
        "signal": bool(trend_sig or drift_sig),
    }


def compute_trends(df, grain_label):
    """df columns: key, name, category, ds, y. Returns per-SKU and per-category
    momentum records (pure - no DB, fully testable)."""
    season = _season(grain_label)
    df = df.copy()
    df["ds"] = pd.to_datetime(df["ds"])

    skus = []
    for key, g in df.sort_values("ds").groupby("key"):
        g = g.groupby("ds", as_index=False)["y"].sum().sort_values("ds")
        rec = series_momentum(g["y"].to_numpy(), season)
        first = df[df["key"] == key].iloc[0]
        skus.append({"key": key, "name": first["name"],
                     "category": first.get("category") or "Uncategorized", **rec})

    cats = []
    for cat, g in df.groupby(df["category"].fillna("Uncategorized")):
        series = g.groupby("ds")["y"].sum().sort_index()
        rec = series_momentum(series.to_numpy(), season)
        cats.append({"category": cat, "n_skus": int(g["key"].nunique()), **rec})

    return {"grain": grain_label, "season": season, "skus": skus, "categories": cats}


# --- ranking helpers (also deterministic) ---------------------------------

def _has(rec, metric):
    return rec.get(metric) is not None


# significance flag that pairs with each rankable metric
_SIG = {"trend_yr": "trend_sig", "g12": "g12_sig"}


def top_movers(records, direction="up", metric="trend_yr", min_units=5.0, limit=5, require_sig=True):
    """Biggest growers (direction='up') or decliners ('down') by `metric`, with a
    volume floor and (default) a significance gate so noise-driven tiny SKUs and
    spurious ratios never rank."""
    sig = _SIG.get(metric)
    pool = [r for r in records
            if _has(r, metric) and r.get("recent_units", 0) >= min_units
            and (not require_sig or not sig or r.get(sig))]
    pool = [r for r in pool if (r[metric] > 0) == (direction == "up") and r[metric] != 0]
    pool.sort(key=lambda r: r[metric], reverse=(direction == "up"))
    return pool[:limit]


def quiet_movers(records, min_streak=3, band=(0.05, 0.30), min_units=5.0, limit=10):
    """Sustained drifts a single ±30% YoY alert would miss: a statistically real
    drift (`drift_sig`, a t-test on recent YoY deltas - the noise guard) that is
    also a multi-period same-sign streak, with a real-but-sub-threshold (<30%)
    annual change. drift_sig is what keeps random noise out."""
    lo, hi = band
    out = []
    for r in records:
        g12 = r.get("g12")
        if g12 is None or r.get("recent_units", 0) < min_units:
            continue
        if r.get("drift_sig") and abs(r.get("streak", 0)) >= min_streak and lo <= abs(g12) < hi:
            out.append(r)
    out.sort(key=lambda r: (abs(r["streak"]), abs(r["g12"])), reverse=True)
    return out[:limit]


def find(records, query):
    """Match a SKU/category record by key, name, or category substring."""
    q = (query or "").strip().lower()
    if not q:
        return []
    hits = [r for r in records
            if q in str(r.get("key", "")).lower()
            or q in str(r.get("name", "")).lower()
            or q in str(r.get("category", "")).lower()]
    return hits


def catalog_trends():
    """DB-backed entry point: assemble the panel from the stored catalog (already
    grain-resampled) and compute momentum. Used by the assistant's trend tool."""
    from app.controllers.catalog_controller import catalog_to_json_data
    from app.forecasting.base import WEEKLY

    json_data, ctx_by_key, grain = catalog_to_json_data()
    label = "weekly" if grain is WEEKLY else "monthly"
    rows = []
    for r in json_data:
        key = r.get("sku") or r.get("product_name")
        rows.append({
            "key": key, "name": r.get("product_name"), "sku": r.get("sku"),
            "category": (ctx_by_key.get(key) or {}).get("Category") or "Uncategorized",
            "ds": r["ds"], "y": r["y"],
        })
    if not rows:
        return {"grain": label, "season": _season(label), "skus": [], "categories": []}
    df = pd.DataFrame(rows)
    df["ds"] = pd.to_datetime(df["ds"])
    # Drop a partial trailing period: the weekly resample buckets by week-ending
    # Sunday, so an unfinished current week would poison every trailing metric.
    # (Monthly catalogs come from whole-month spreadsheet columns, so complete.)
    if label == "weekly":
        from app.extensions import db
        from app.models.sales_record import SalesRecord
        last_raw = db.session.query(db.func.max(SalesRecord.date)).scalar()
        last_period = df["ds"].max()
        if last_raw is not None and pd.Timestamp(last_raw) < last_period:
            df = df[df["ds"] < last_period]
    return compute_trends(df, label)
