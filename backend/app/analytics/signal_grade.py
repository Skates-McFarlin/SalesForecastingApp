"""Grade the intelligence layer's SIGNALS against what actually happened next.

The forecast has a track record (the ledger); the ATTENTION signals -
"declining", "quiet drift", "abrupt step down" - did not. But that's what a
seller judges us on: did Insighta cry wolf? With hundreds of SKUs, Mann-Kendall
and changepoint detection will fire by chance, so a *realized* false-alarm rate is
the honest trust artifact.

Because the signals are deterministic and we hold the full history, we grade them
by BACKTEST (no new persistence): at each of several past cutoffs, recompute the
signal from data up to the cutoff, then check whether the SUSTAINED level kept
moving in the claimed direction over the next `horizon` periods.

Grading on a single next-window YoY is biased against the layer by mean reversion
(a signal fired on a recent dip tends to bounce, an unfair "miss"). So we grade on
the TRAILING-ANNUAL-SUM (a rolling 12-period sum - seasonality-free, and exactly
the quantity the sustained-trend signal is built on): a "down" signal HITS if that
annual level is lower `horizon` periods later than at the cutoff. Aggregated across
the catalog, that's an honest "of the declines we flagged, how many kept declining"
number. (Consecutive annual sums overlap, so this measures trend CONTINUATION, not
a fresh independent window - the right question for a sustained-trend claim.)
"""
import numpy as np

from .trends import series_momentum, _season

# A per-(type,direction) weight is only trusted with enough graded samples -
# otherwise a lucky small-n bucket shows a large spurious lift (the multiple-
# testing trap). Below this, weight is 0 (the ranking falls back to raw priority).
MIN_GRADED = 30


def _direction(rec):
    """+1 if the record carries an up-signal, -1 a down-signal, 0 if none - using
    the same signals the app surfaces (pattern, significant trend, real drift)."""
    down = (rec.get("pattern") in ("gradual_decline", "abrupt_drop")
            or (rec.get("trend_sig") and (rec.get("trend_yr") or 0) < 0)
            or (rec.get("drift_sig") and rec.get("streak", 0) < 0))
    up = (rec.get("pattern") in ("gradual_rise", "abrupt_rise")
          or (rec.get("trend_sig") and (rec.get("trend_yr") or 0) > 0)
          or (rec.get("drift_sig") and rec.get("streak", 0) > 0))
    if down and not up:
        return -1
    if up and not down:
        return 1
    return 0


def _label(rec, direction):
    p = rec.get("pattern")
    if p in ("abrupt_drop", "abrupt_rise"):
        return "shift"
    if rec.get("drift_sig") and not rec.get("trend_sig"):
        return "drift"
    return "trend"


def grade_series(y, season, horizon=3, max_origins=6):
    """Backtest one series at each cutoff. Records EVERY cutoff (not just the ones a
    signal fired on) so the caller can compute the unconditional continuation base
    rate - a hit-rate is meaningless without it. Each record: signal direction `sig`
    (-1/0/+1), its `type`, and the realized continuation direction `realized_dir`
    (sign of the trailing-annual-sum change `horizon` periods later)."""
    y = np.asarray(y, dtype=float)
    n = len(y)
    min_hist = 2 * season
    out = []
    c = n - horizon
    graded = 0
    while c >= min_hist:
        if c - season >= 0:
            base_lvl = float(y[c - season:c].sum())
            fut_lvl = float(y[c + horizon - season:c + horizon].sum())
            if base_lvl > 0:
                rec = series_momentum(y[:c], season)
                d = _direction(rec)
                realized = fut_lvl / base_lvl - 1.0
                out.append({"cut": c, "sig": d, "type": _label(rec, d) if d else None,
                            "realized_dir": -1 if realized < 0 else (1 if realized > 0 else 0)})
                if d != 0:
                    graded += 1
                    if graded >= max_origins:
                        break
        c -= horizon
    return out


def grade_panel(df, grain_label, horizon=3):
    """Grade every SKU's signals over a panel (columns key, ds, y). Returns
    {n_signals, hits, hit_rate, false_alarm_rate, by_type}."""
    import pandas as pd

    season = _season(grain_label)
    df = df.copy()
    df["ds"] = pd.to_datetime(df["ds"])
    grades = []
    for _, g in df.sort_values("ds").groupby("key"):
        s = g.groupby("ds", as_index=False)["y"].sum().sort_values("ds")
        grades.extend(grade_series(s["y"].to_numpy(), season, horizon))
    return summarize(grades)


def summarize(records):
    """Aggregate cutoff records into base rates + per-(type, direction) hit-rate,
    LIFT over the base rate, and a predictive `weight` (max(0, lift) - anti-
    predictive signals get 0, so gating suppresses them). `weights` is the flat map
    the ranking layers consume, keyed 'type_up'/'type_down'."""
    total = len(records)
    fired = [r for r in records if r["sig"] != 0]
    if not total:
        return {"n_signals": 0, "hit_rate": None, "base_down": None, "base_up": None,
                "by_type": {}, "weights": {}}
    base_down = sum(1 for r in records if r["realized_dir"] < 0) / total
    base_up = sum(1 for r in records if r["realized_dir"] > 0) / total

    groups = {}   # (type, dir) -> [n, hits]
    for r in fired:
        key = (r["type"], "down" if r["sig"] < 0 else "up")
        g = groups.setdefault(key, [0, 0])
        g[0] += 1
        g[1] += int(r["realized_dir"] == r["sig"])

    by_type, weights = {}, {}
    for (t, d), (n, hits) in groups.items():
        hit = hits / n
        base = base_down if d == "down" else base_up
        lift = hit - base
        by_type[f"{t}_{d}"] = {"n": n, "hit_rate": round(hit, 3),
                               "base_rate": round(base, 3), "lift": round(lift, 3)}
        # 0 => not surfaced (anti-predictive, or too few samples to trust).
        weights[f"{t}_{d}"] = round(max(0.0, lift), 3) if n >= MIN_GRADED else 0.0
    hits = sum(1 for r in fired if r["realized_dir"] == r["sig"])
    return {
        "n_signals": len(fired),
        "hit_rate": round(hits / len(fired), 3) if fired else None,
        "base_down": round(base_down, 3), "base_up": round(base_up, 3),
        "by_type": by_type, "weights": weights,
    }


def catalog_signal_grade(horizon=3):
    """DB-backed: grade the stored catalog's signals. Same panel the trend layer
    uses, so 'what we flag' and 'how we grade it' stay in lockstep."""
    import pandas as pd

    from app.controllers.catalog_controller import catalog_to_json_data
    from app.forecasting.base import WEEKLY

    json_data, ctx_by_key, grain = catalog_to_json_data()
    label = "weekly" if grain is WEEKLY else "monthly"
    if not json_data:
        return summarize([])
    rows = [{"key": r.get("sku") or r.get("product_name"), "ds": r["ds"], "y": r["y"]}
            for r in json_data]
    return grade_panel(pd.DataFrame(rows), label, horizon)
