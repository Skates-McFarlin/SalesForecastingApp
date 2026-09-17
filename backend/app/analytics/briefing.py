"""Proactive briefing.

Composes the intelligence primitives (trends, trust, and - when the frontend has
run a forecast - attention/exceptions) into a short, PRIORITIZED "here's what
matters" the assistant can lead with, unprompted. The smartness is selection:
surface the few things worth a small seller's attention, ranked by urgency, and
stay quiet on a calm catalog rather than manufacturing drama. Deterministic and
testable; the model only phrases the selected items.
"""


def _pct(x):
    return f"{x * 100:+.0f}%" if x is not None else "n/a"


_GROUNDED = {"stockout", "overdue"}   # current facts, never reliability-gated


def build_briefing(trends, trust, attention=None, limit=5, weights=None):
    """Rank the noteworthy items from the computed signals. Returns a list of
    {priority, kind, subject, detail}, best first, capped at `limit`. `attention`
    (optional) = {stockout, overdue, ...} counts from the client.

    Base priority: 5 stockout/overdue (act now) > 4 sharp category decline > 3 quiet
    drift / big SKU decline > 2 growth > 1 low-trust. When `weights` (a
    {type_direction: predictive_weight} map from the signal backtest, where weight =
    max(0, hit_rate - base_rate)) is given, trend-family items are RANKED by
    priority x weight, and ANTI-PREDICTIVE signal types (weight 0 - they hit below
    the base rate, e.g. up-trend/up-shift on M5) are DROPPED entirely rather than
    surfaced. Grounded inventory facts (stockout/overdue) are never gated - they're
    true now, not predictions - and the reliable quiet-drift (lift ~+20pt) leads.
    """
    from app.analytics.trends import top_movers, quiet_movers, recent_shifts
    from app.analytics.trust import least_trusted

    cats, skus = trends.get("categories", []), trends.get("skus", [])
    vol = {r["key"]: r.get("recent_units", 0) for r in skus}
    items = []

    # 5 - urgent, only when the client passed live inventory/forecast state
    a = attention or {}
    if a.get("stockout"):
        items.append({"priority": 5, "kind": "stockout", "subject": f"{a['stockout']} products",
                      "detail": "at stockout risk right now"})
    if a.get("overdue"):
        items.append({"priority": 5, "kind": "overdue", "subject": f"{a['overdue']} deliveries",
                      "detail": "overdue from suppliers"})

    # 4 - a whole category sliding
    for c in top_movers(cats, "down", "trend_yr", limit=2):
        items.append({"priority": 4, "kind": "category_down", "sig_key": "trend_down",
                      "subject": c["category"],
                      "detail": f"sustained {_pct(c['trend_yr'])}/yr decline across the category"})

    # 4/3 - an abrupt LEVEL SHIFT in the last half-year: a discrete "something
    # happened here" event, a different (often more actionable) story than a slow
    # drift. Freshest first; recent drops outrank recent rises.
    within = max(3, trends.get("season", 12) // 2)
    for s in recent_shifts(skus, within=within, limit=3):
        sh = s["shift"]; ago = sh["periods_ago"]; down = sh["rel_change"] < 0
        items.append({"priority": 4 if down else 3, "kind": "shift",
                      "sig_key": "shift_down" if down else "shift_up", "subject": s["name"],
                      "detail": f"stepped {'down' if down else 'up'} {_pct(sh['rel_change'])} about "
                                f"{ago} period{'' if ago == 1 else 's'} ago - an abrupt change, not a slow drift"})

    # 3 - quiet drifts (below the usual alert) + the single biggest SKU decline
    for s in quiet_movers(skus, limit=2):
        items.append({"priority": 3, "kind": "quiet_drift",
                      "sig_key": "drift_up" if s["streak"] > 0 else "drift_down", "subject": s["name"],
                      "detail": f"{'up' if s['streak'] > 0 else 'down'} {abs(s['streak'])} periods "
                                f"({_pct(s['g12'])} YoY) - below a normal alert"})
    for s in top_movers(skus, "down", "trend_yr", limit=1):
        items.append({"priority": 3, "kind": "sku_down", "sig_key": "trend_down", "subject": s["name"],
                      "detail": f"declining {_pct(s['trend_yr'])}/yr"})

    # 2 - growth that may need supply to keep up
    for c in top_movers(cats, "up", "trend_yr", limit=1):
        items.append({"priority": 2, "kind": "category_up", "sig_key": "trend_up",
                      "subject": c["category"],
                      "detail": f"growing {_pct(c['trend_yr'])}/yr - make sure supply keeps up"})

    # 1 - a low-trust forecast on a product that actually matters (high volume)
    low = [r for r in least_trusted(trust.get("skus", []), limit=20)]
    low.sort(key=lambda r: vol.get(r["key"], 0), reverse=True)
    for r in low[:1]:
        if vol.get(r["key"], 0) > 0:
            items.append({"priority": 1, "kind": "low_trust", "subject": r["name"],
                          "detail": f"a high-volume product with a shaky forecast ({r['score']}/100: {r['reasons'][0]})"})

    # de-dupe by subject (one line per product/category - don't bill the same
    # thing twice, e.g. a stepped-down SKU that's also a slow decliner), keeping
    # its highest-priority framing, then rank.
    seen = {}
    for it in items:
        k = it["subject"]
        if k not in seen or it["priority"] > seen[k]["priority"]:
            seen[k] = it

    def weight_of(it):
        if it["kind"] in _GROUNDED or it["kind"] == "low_trust":
            return None                          # not a graded signal
        return (weights or {}).get(it.get("sig_key"))

    # Drop signals measured to be ANTI-predictive (weight exactly 0): surfacing a
    # flag that hits below its base rate is worse than staying quiet.
    kept = [it for it in seen.values() if weight_of(it) != 0]

    def score(it):
        if it["kind"] in _GROUNDED:
            return 100 + it["priority"]          # grounded facts always lead
        if it["kind"] == "low_trust":
            return -1                            # a caveat, always last
        w = weight_of(it)
        # priority x predictive lift; falls back to raw priority when not graded.
        return it["priority"] * w if w is not None else it["priority"]

    ranked = sorted(kept, key=score, reverse=True)
    return ranked[:limit]


def catalog_briefing(attention=None, limit=5):
    """DB-backed briefing over the stored catalog, gated by the signal backtest's
    per-(type,direction) predictive lift so anti-predictive signal types are
    dropped and reliable ones lead (see app.analytics.signal_grade)."""
    from app.analytics.trends import catalog_trends
    from app.analytics.trust import catalog_trust
    from app.analytics.signal_grade import catalog_signal_grade

    weights = None
    try:
        weights = catalog_signal_grade().get("weights") or None
    except Exception:  # noqa: BLE001 - gating is best-effort; fall back to raw priority
        weights = None
    return build_briefing(catalog_trends(), catalog_trust(), attention=attention,
                          limit=limit, weights=weights)
