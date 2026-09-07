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
import math

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

# Shift-vs-drift thresholds. A "gradual drift" and an "abrupt shift" are DIFFERENT
# shapes and want different detectors: a monotonic trend (Mann-Kendall) vs a
# discrete level jump (changepoint). Labelling them apart deterministically is the
# point - a small narrator model guesses this distinction wrong, so we hand it the
# answer instead of the raw numbers.
MK_Z = 1.96             # Mann-Kendall |z| for a significant monotonic trend (p<0.05)
# _best_split picks the MAX t over ~n candidate positions, so its null isn't a
# single t: pure noise throws a spurious ~t=3 split routinely. Real steps clear
# t>=15, so a high bar (that accounts for the search) keeps false shifts out
# without missing genuine ones.
STEP_T = 4.5            # two-sample t across the best split to call a real step
STEP_REL = 0.15         # ...and the step must move the level at least 15%
MIN_SEG = 3             # min periods on each side of a changepoint


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


def _deseasonalize(y, season):
    """Divide out MULTIPLICATIVE seasonality (each phase's level ratio) so the
    trend/changepoint detectors see LEVEL, not the calendar turning. Multiplicative
    (not additive) keeps the result NON-NEGATIVE - additive subtraction on a
    near-zero-floor seasonal item (a holiday SKU) drives off-season months negative
    and leaves a residual peak that reads as a phantom step. Indices are floored so
    a near-zero phase can't explode the division."""
    if len(y) < 2 * season or season < 2:
        return y.astype(float)
    overall = float(y.mean())
    if overall <= 0:
        return y.astype(float)
    phase = np.arange(len(y)) % season
    idx = np.array([max(y[phase == p].mean() / overall, 0.1) for p in range(season)])
    return y / idx[phase]


def _norm_cdf(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _mann_kendall(d):
    """Non-parametric monotonic-trend test (tie-corrected, normal approximation).
    Returns (z, direction) where direction is +1 rising / -1 falling / 0 none.
    Robust to outliers and makes no linearity assumption - it answers 'is the
    series drifting one way, gradually?' which is the complement of a step."""
    n = len(d)
    if n < 8:
        return 0.0, 0
    s = 0
    for i in range(n - 1):
        s += int(np.sum(np.sign(d[i + 1:] - d[i])))
    _, counts = np.unique(d, return_counts=True)
    ties = float(np.sum(counts * (counts - 1) * (2 * counts + 5)))
    var = (n * (n - 1) * (2 * n + 5) - ties) / 18.0
    if var <= 0:
        return 0.0, 0
    if s > 0:
        z = (s - 1) / math.sqrt(var)
    elif s < 0:
        z = (s + 1) / math.sqrt(var)
    else:
        z = 0.0
    direction = int(np.sign(z)) if abs(z) >= MK_Z else 0
    return round(float(z), 3), direction


def _best_split(d):
    """Best single mean-shift changepoint by minimizing within-segment SSE, via
    prefix sums (O(n)). Returns (t, sse_step) where t is the newest segment's start
    index, or (None, sse_total) when the series is too short to split."""
    n = len(d)
    tot = float(((d - d.mean()) ** 2).sum())
    if n < 2 * MIN_SEG:
        return None, tot
    p1 = np.concatenate([[0.0], np.cumsum(d)])
    p2 = np.concatenate([[0.0], np.cumsum(d * d)])

    def sse(a, b):
        cnt = b - a
        s = p1[b] - p1[a]
        return (p2[b] - p2[a]) - s * s / cnt

    best_t, best = None, math.inf
    for t in range(MIN_SEG, n - MIN_SEG + 1):
        cur = sse(0, t) + sse(t, n)
        if cur < best:
            best, best_t = cur, t
    return best_t, best


def _changepoint(d):
    """Detect a discrete level shift and score its confidence. Returns a dict
    (periods_ago from the series end, from/to level, relative move, two-sample t)
    when a real step is present, else None. A ramp also 'splits' well, so the
    caller must still compare this against a linear fit before calling it abrupt.

    The step must be big relative to the series' TYPICAL volume (mean), not just
    the possibly-tiny left segment - and `rel_change` is reported against a
    mean-floored denominator so a near-zero prior level can never produce an
    impossible (< -100% or exploding) percentage."""
    n = len(d)
    t, sse_step = _best_split(d)
    if t is None:
        return None
    left, right = d[:t], d[t:]
    ml, mr = float(left.mean()), float(right.mean())
    nl, nr = len(left), len(right)
    mu = float(np.mean(d))
    pooled_var = sse_step / max(n - 2, 1)
    denom = math.sqrt(pooled_var * (1.0 / nl + 1.0 / nr)) if pooled_var > 0 else 0.0
    tstat = abs(mr - ml) / denom if denom > 0 else (math.inf if mr != ml else 0.0)
    # Magnitude gate is against typical volume; % is against a floored prior level.
    if tstat < STEP_T or mu <= 0 or abs(mr - ml) < STEP_REL * mu:
        return None
    rel = (mr - ml) / max(abs(ml), 0.25 * mu)
    return {"periods_ago": int(n - t), "from_level": round(ml, 2),
            "to_level": round(mr, 2), "rel_change": round(float(rel), 4),
            "t": round(float(tstat), 2) if math.isfinite(tstat) else 99.0,
            "sse_step": float(sse_step)}


def _pattern(y, season):
    """Label the series' SHAPE: an abrupt level shift vs a gradual monotonic drift
    vs steady. Deseasonalize first (else every season reads as a shift), then run
    both detectors and let the better-fitting model win: a step is only 'abrupt' if
    the two-mean fit beats a straight line - otherwise a genuine ramp that happens
    to split gets mislabeled. This is the shift/drift call a small model can't make
    reliably; we compute it so the narrator just reports it."""
    y = np.asarray(y, dtype=float)
    out = {"pattern": "steady", "shift": None, "mk_z": 0.0}
    # Measure the ACTIVE series (trim leading pre-launch zeros): a launch is a
    # launch, not an abrupt step, and leading zeros make the prior level ~0 and
    # explode the %. A step can't be told apart from a season without a couple of
    # clean cycles, so short-active series get no shift/trend claim - honest.
    nz = np.nonzero(y > 0)[0]
    if len(nz):
        y = y[nz[0]:]
    if len(y) < max(8, 2 * season):
        return out
    d = _deseasonalize(y, season)
    n = len(d)
    mk_z, mk_dir = _mann_kendall(d)
    out["mk_z"] = mk_z
    cp = _changepoint(d)
    if cp is not None:
        x = np.arange(n)
        slope, intercept = np.polyfit(x, d, 1)
        sse_line = float(((d - (slope * x + intercept)) ** 2).sum())
        # A step must explain the series at least as well as a straight ramp.
        if cp["sse_step"] <= sse_line:
            out["shift"] = {k: v for k, v in cp.items() if k != "sse_step"}
            out["pattern"] = "abrupt_rise" if cp["rel_change"] > 0 else "abrupt_drop"
            return out
    if mk_dir > 0:
        out["pattern"] = "gradual_rise"
    elif mk_dir < 0:
        out["pattern"] = "gradual_decline"
    return out


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
    shape = _pattern(y, season)
    # Cross-check the GRADUAL label against the independent R^2-gated rolling-sum
    # trend: a real monotonic drift clears both detectors; a deseasonalization
    # artifact clears only Mann-Kendall. (Abrupt shifts keep their changepoint
    # evidence and aren't gated on trend_sig.)
    if shape["pattern"] in ("gradual_rise", "gradual_decline") and not trend_sig:
        shape["pattern"] = "steady"
    return {
        "trend_yr": trend_yr, "trend_sig": trend_sig,   # sustained direction + is-it-real
        "g3": g3, "g6": _yoy_growth(y, 6, season),
        "g12": g12, "g12_sig": bool(g12_sig),           # annual YoY + is-it-real
        "accel": accel,                                 # recent pace vs annual pace
        "streak": streak, "drift_sig": bool(drift_sig), # consecutive YoY periods + is-the-drift-real
        "pattern": shape["pattern"],                    # abrupt_rise/drop | gradual_rise/decline | steady
        "shift": shape["shift"],                        # dict when an abrupt step is present, else None
        "mk_z": shape["mk_z"],                          # Mann-Kendall z (monotonic-trend evidence)
        "recent_units": round(float(y[-season:].sum()) if len(y) >= season else float(y.sum()), 1),
        "cv": round(cv, 3), "n_periods": int(len(y)),
        # Worth a comment only if a real sustained trend, a significant drift, or a step.
        "signal": bool(trend_sig or drift_sig or shape["shift"] is not None),
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


def recent_shifts(records, within=None, min_units=5.0, limit=10):
    """SKUs/categories that took an abrupt level STEP recently (a discrete jump the
    gradual-trend metrics blur over). `within` bounds how many periods back the step
    may be (default: any); results are the freshest, largest steps first."""
    out = []
    for r in records:
        sh = r.get("shift")
        if sh is None or r.get("recent_units", 0) < min_units:
            continue
        if within is not None and sh.get("periods_ago", 10 ** 9) > within:
            continue
        out.append(r)
    out.sort(key=lambda r: (-r["shift"]["periods_ago"], abs(r["shift"]["rel_change"])),
             reverse=True)
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
