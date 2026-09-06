"""Forecast-trust scoring.

How much should you trust a given SKU's forecast? Some products are inherently
predictable (long, smooth, regular history); others are guesses dressed as
numbers (a few months of on-and-off demand). This turns that into a deterministic
0-100 score + a plain-language reason, so the assistant can be honest about
confidence - "up 18%, but low-trust: only 8 months of history and lumpy demand" -
instead of stating every forecast with equal certainty.

Signals, all from sales history (no forecast or ledger needed, so it works
immediately): history depth, demand regularity (the same Syntetos-Boylan ADI/CV^2
split the engine routes on), and overall volatility. Optional enrichment from the
forecast interval and the ledger can be layered later.
"""
import numpy as np

from app.forecasting.intermittent import ADI_CUT, CV2_CUT


def _classify(y, season):
    """Return (pattern, adi, cv2, cv) using the engine's own demand-pattern cuts
    so trust agrees with how the forecaster actually treats the SKU."""
    y = np.asarray(y, dtype=float)
    nz = y[y > 0]
    mean = float(y.mean()) if len(y) else 0.0
    cv = float(y.std() / mean) if mean > 0 else 0.0
    if len(nz) == 0:
        return "no-demand", float("inf"), 0.0, cv
    adi = len(y) / len(nz)                    # avg inter-demand interval
    mean_nz = float(nz.mean())
    cv2 = float((nz.std() / mean_nz) ** 2) if mean_nz > 0 else 0.0
    if adi >= ADI_CUT and cv2 >= CV2_CUT:
        pat = "lumpy"
    elif adi >= ADI_CUT:
        pat = "intermittent"
    elif cv2 >= CV2_CUT:
        pat = "erratic"
    else:
        pat = "smooth"
    return pat, adi, cv2, cv


def series_trust(y, season):
    """{score 0-100, level, pattern, reasons[]} for one demand series."""
    y = np.asarray(y, dtype=float)
    nz_idx = np.nonzero(y > 0)[0]
    if len(nz_idx) == 0:
        return {"score": 5, "level": "low", "pattern": "no-demand", "n_periods": len(y),
                "reasons": ["no recorded sales to forecast from"]}
    # Measure on the ACTIVE history - from the first real sale onward. Leading
    # zeros (pre-launch) aren't "history" and would fake a long, gappy series.
    active = y[nz_idx[0]:]
    n = len(active)
    pat, adi, cv2, cv = _classify(active, season)

    score = 100
    reasons = []

    # History depth, in years of active selling - the more you've seen, the more
    # a forecast is measurement rather than guesswork.
    if n < season:
        score -= 55; reasons.append(f"under a year of sales history ({n} periods)")
    elif n < 2 * season:
        score -= 25; reasons.append(f"under two years of history ({n} periods)")

    # Demand regularity, built from the two things that make demand un-forecastable:
    # gaps (high inter-demand interval) and variable order size (high CV^2).
    if adi >= ADI_CUT and cv2 >= CV2_CUT:      # lumpy - the worst of both
        score -= 55; reasons.append("lumpy: sporadic, and variable when it does sell")
    elif adi >= ADI_CUT:                        # intermittent - on and off
        score -= 35; reasons.append("intermittent on-and-off demand")
    elif cv2 >= CV2_CUT:                        # erratic - regular but swingy
        score -= 20; reasons.append("sells regularly but in very variable amounts")

    score = int(max(0, min(100, score)))
    level = "high" if score >= 72 else "medium" if score >= 48 else "low"
    if not reasons:  # high-trust SKU - say why it's trustworthy
        yrs = n / season
        reasons.append(f"{yrs:.0f}+ years of steady, regular history" if yrs >= 2
                       else "regular, predictable demand")
    return {"score": score, "level": level, "pattern": pat, "cv": round(cv, 2),
            "n_periods": n, "reasons": reasons}


def compute_trust(df, grain_label):
    """df columns: key, name, category, ds, y. Per-SKU trust (pure/testable)."""
    import pandas as pd
    season = 52 if grain_label == "weekly" else 12
    df = df.copy(); df["ds"] = pd.to_datetime(df["ds"])
    out = []
    for key, g in df.sort_values("ds").groupby("key"):
        s = g.groupby("ds", as_index=False)["y"].sum().sort_values("ds")
        rec = series_trust(s["y"].to_numpy(), season)
        first = df[df["key"] == key].iloc[0]
        out.append({"key": key, "name": first["name"],
                    "category": first.get("category") or "Uncategorized", **rec})
    return {"grain": grain_label, "skus": out}


def least_trusted(records, max_level="low", min_units=0.0, limit=5):
    """SKUs whose forecasts deserve the most caution (lowest score first)."""
    order = {"low": 0, "medium": 1, "high": 2}
    cap = order.get(max_level, 0)
    pool = [r for r in records if order.get(r["level"], 2) <= cap]
    pool.sort(key=lambda r: r["score"])
    return pool[:limit]


def catalog_trust():
    """DB-backed entry point: per-SKU forecast trust over the stored catalog."""
    import pandas as pd
    from app.controllers.catalog_controller import catalog_to_json_data
    from app.forecasting.base import WEEKLY

    json_data, ctx_by_key, grain = catalog_to_json_data()
    label = "weekly" if grain is WEEKLY else "monthly"
    rows = []
    for r in json_data:
        key = r.get("sku") or r.get("product_name")
        rows.append({"key": key, "name": r.get("product_name"), "sku": r.get("sku"),
                     "category": (ctx_by_key.get(key) or {}).get("Category") or "Uncategorized",
                     "ds": r["ds"], "y": r["y"]})
    if not rows:
        return {"grain": label, "skus": []}
    return compute_trust(pd.DataFrame(rows), label)
