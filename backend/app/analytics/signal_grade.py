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
    """Backtest one series' signals. Returns a list of graded signals
    {cut, dir, type, realized_yoy, hit}. Cutoffs step back by `horizon` (so the
    graded windows don't overlap) from the latest point that still leaves `horizon`
    future periods; each needs a full year of history plus the YoY comparison base."""
    y = np.asarray(y, dtype=float)
    n = len(y)
    min_hist = 2 * season
    out = []
    c = n - horizon
    while c >= min_hist and len(out) < max_origins:
        if c - season >= 0:
            rec = series_momentum(y[:c], season)
            d = _direction(rec)
            base_lvl = float(y[c - season:c].sum())            # trailing annual sum at cut
            fut_lvl = float(y[c + horizon - season:c + horizon].sum())  # ...`horizon` later
            if d != 0 and base_lvl > 0:
                realized = fut_lvl / base_lvl - 1.0            # change in sustained level
                hit = realized < 0 if d < 0 else realized > 0
                out.append({"cut": c, "dir": d, "type": _label(rec, d),
                            "realized": round(realized, 3), "hit": bool(hit)})
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


def summarize(grades):
    n = len(grades)
    if not n:
        return {"n_signals": 0, "hits": 0, "hit_rate": None,
                "false_alarm_rate": None, "by_type": {}}
    hits = sum(1 for g in grades if g["hit"])
    by_type = {}
    for g in grades:
        t = by_type.setdefault(g["type"], {"n": 0, "hits": 0})
        t["n"] += 1
        t["hits"] += int(g["hit"])
    for t in by_type.values():
        t["hit_rate"] = round(t["hits"] / t["n"], 3)
    return {
        "n_signals": n, "hits": hits,
        "hit_rate": round(hits / n, 3),
        "false_alarm_rate": round(1 - hits / n, 3),
        "by_type": by_type,
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
