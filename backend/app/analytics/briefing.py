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


# Which graded signal type each trend-family item is an instance of, so its
# ranking can be discounted by that type's measured forward reliability.
_KIND_SIGNAL = {"category_down": "trend", "sku_down": "trend", "category_up": "trend",
                "quiet_drift": "drift", "shift": "shift"}
_GROUNDED = {"stockout", "overdue"}   # current facts, never reliability-gated


def build_briefing(trends, trust, attention=None, limit=5, reliability=None):
    """Rank the noteworthy items from the computed signals. Returns a list of
    {priority, kind, subject, detail}, best first, capped at `limit`. `attention`
    (optional) = {stockout, overdue, ...} counts from the client.

    Base priority: 5 stockout/overdue (act now) > 4 sharp category decline > 3 quiet
    drift / big SKU decline > 2 growth needing supply > 1 low-trust. When
    `reliability` (a {signal_type: hit_rate} map from the signal backtest) is given,
    the trend-family items are RANKED by base-priority x reliability, so the signal
    types that actually pan out (measured: quiet drift ~0.65) float above the ones
    that mostly mean-revert (a lone trend/step ~0.4-0.48). Grounded inventory facts
    (stockout/overdue) are never gated - they're true now, not predictions.
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
        items.append({"priority": 4, "kind": "category_down", "subject": c["category"],
                      "detail": f"sustained {_pct(c['trend_yr'])}/yr decline across the category"})

    # 4/3 - an abrupt LEVEL SHIFT in the last half-year: a discrete "something
    # happened here" event, a different (often more actionable) story than a slow
    # drift. Freshest first; recent drops outrank recent rises.
    within = max(3, trends.get("season", 12) // 2)
    for s in recent_shifts(skus, within=within, limit=3):
        sh = s["shift"]; ago = sh["periods_ago"]; down = sh["rel_change"] < 0
        items.append({"priority": 4 if down else 3, "kind": "shift", "subject": s["name"],
                      "detail": f"stepped {'down' if down else 'up'} {_pct(sh['rel_change'])} about "
                                f"{ago} period{'' if ago == 1 else 's'} ago - an abrupt change, not a slow drift"})

    # 3 - quiet drifts (below the usual alert) + the single biggest SKU decline
    for s in quiet_movers(skus, limit=2):
        items.append({"priority": 3, "kind": "quiet_drift", "subject": s["name"],
                      "detail": f"{'up' if s['streak'] > 0 else 'down'} {abs(s['streak'])} periods "
                                f"({_pct(s['g12'])} YoY) - below a normal alert"})
    for s in top_movers(skus, "down", "trend_yr", limit=1):
        items.append({"priority": 3, "kind": "sku_down", "subject": s["name"],
                      "detail": f"declining {_pct(s['trend_yr'])}/yr"})

    # 2 - growth that may need supply to keep up
    for c in top_movers(cats, "up", "trend_yr", limit=1):
        items.append({"priority": 2, "kind": "category_up", "subject": c["category"],
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

    def score(it):
        if it["kind"] in _GROUNDED:
            return 100 + it["priority"]          # grounded facts always lead
        if it["kind"] == "low_trust":
            return -1                            # a caveat, always last
        rel = (reliability or {}).get(_KIND_SIGNAL.get(it["kind"]))
        # Reliability-weighted urgency = how much it matters x how often it pans
        # out. Falls back to raw priority when the signal type isn't graded yet.
        return it["priority"] * rel if rel is not None else it["priority"]

    ranked = sorted(seen.values(), key=score, reverse=True)
    return ranked[:limit]


def catalog_briefing(attention=None, limit=5):
    """DB-backed briefing over the stored catalog, gated by the signal backtest's
    measured per-type reliability so flaky signal types don't crowd out reliable
    ones (see app.analytics.signal_grade)."""
    from app.analytics.trends import catalog_trends
    from app.analytics.trust import catalog_trust
    from app.analytics.signal_grade import catalog_signal_grade

    reliability = None
    try:
        by_type = catalog_signal_grade().get("by_type", {})
        reliability = {t: v["hit_rate"] for t, v in by_type.items() if v.get("hit_rate") is not None}
    except Exception:  # noqa: BLE001 - gating is best-effort; fall back to raw priority
        reliability = None
    return build_briefing(catalog_trends(), catalog_trust(), attention=attention,
                          limit=limit, reliability=reliability or None)
