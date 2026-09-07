"""The assistant - Phase 6.

Promotes the LLM from summary-writer to something you can TALK TO about your
business: "what needs me?", "how's the parka doing?", "how accurate have you
been?". Comes last on purpose - it's only worth asking once the engine beneath it
is stateful, optimizing, and self-correcting.

Anti-fabrication holds exactly as in the summaries: the app computes every number
(the frontend assembles a snapshot from the real forecast + inventory + ledger),
and the LLM only PHRASES an answer grounded in those facts. Any number it writes
that isn't traceable to the snapshot is caught and it's asked to try again.
"""
from app.controllers.prediction_controller import _chat, _unsupported_numbers
from app.analytics.trends import catalog_trends, top_movers, quiet_movers, recent_shifts
from app.analytics.trust import catalog_trust, least_trusted


_PATTERN_WORDS = {
    "abrupt_rise": "an abrupt step UP", "abrupt_drop": "an abrupt step DOWN",
    "gradual_rise": "a gradual sustained rise", "gradual_decline": "a gradual sustained decline",
    "steady": "steady (no trend or step)",
}


def _pct(x):
    return f"{x * 100:+.0f}%" if x is not None else "n/a"


def _periods(n):
    n = abs(int(n))
    return f"{n} period{'' if n == 1 else 's'}"


def _mentions(name, question):
    """True if the question references this product by a meaningful name word."""
    q = question.lower()
    return any(len(w) >= 4 and w in q for w in str(name).lower().replace("/", " ").split())


def _trend_facts(question):
    """Trend & momentum intelligence (computed server-side over full sales
    history). Always offers the catalog-wide movers; if the question names a
    product, adds that SKU's momentum. These are real, deterministic numbers -
    the model narrates them, never invents them."""
    try:
        t = catalog_trends()
    except Exception:  # noqa: BLE001 - trends are best-effort context
        return []
    skus, cats = t.get("skus", []), t.get("categories", [])
    if not skus:
        return []
    unit = "year" if t.get("grain") == "monthly" else "year"
    lines = ["Trend & momentum (sustained trend is per-year, seasonality-adjusted; "
             "YoY is the last 12 periods vs the year before):"]

    grow_c = top_movers(cats, "up", "trend_yr", limit=3)
    fall_c = top_movers(cats, "down", "trend_yr", limit=3)
    if grow_c:
        lines.append("  Growing categories: " + ", ".join(
            f"{c['category']} {_pct(c['trend_yr'])}/{unit}" for c in grow_c))
    if fall_c:
        lines.append("  Declining categories: " + ", ".join(
            f"{c['category']} {_pct(c['trend_yr'])}/{unit}" for c in fall_c))

    grow_s = top_movers(skus, "up", "trend_yr", limit=5)
    fall_s = top_movers(skus, "down", "trend_yr", limit=5)
    if grow_s:
        lines.append("  Fastest-growing products: " + "; ".join(
            f"{s['name']} {_pct(s['trend_yr'])}/{unit}" for s in grow_s))
    if fall_s:
        lines.append("  Fastest-declining products: " + "; ".join(
            f"{s['name']} {_pct(s['trend_yr'])}/{unit}" for s in fall_s))

    quiet = quiet_movers(skus, min_streak=3, limit=5)
    if quiet:
        lines.append("  Quiet drifts (sustained, below a +/-30% YoY alert): " + "; ".join(
            f"{s['name']} {'up' if s['streak'] > 0 else 'down'} {_periods(s['streak'])}, "
            f"{_pct(s['g12'])} YoY" for s in quiet))

    # Abrupt LEVEL SHIFTS in the last half-year: a discrete step is a different
    # story than a slow drift, and the labels are computed (changepoint vs
    # Mann-Kendall) so the model never has to guess shift-vs-drift.
    within = max(3, t.get("season", 12) // 2)
    shifts = recent_shifts(skus, within=within, limit=4)
    if shifts:
        lines.append("  Abrupt shifts (a step change, not a slow drift): " + "; ".join(
            f"{s['name']} stepped {'down' if s['shift']['rel_change'] < 0 else 'up'} "
            f"{_pct(s['shift']['rel_change'])} ~{_periods(s['shift']['periods_ago'])} ago"
            for s in shifts))

    seen = set()
    named = [s for s in skus if _mentions(s["name"], question)
             and not (s["name"] in seen or seen.add(s["name"]))][:3]
    for s in named:
        line = (
            f"  Momentum for {s['name']}: {_PATTERN_WORDS.get(s.get('pattern'), s.get('pattern'))}; "
            f"sustained {_pct(s['trend_yr'])}/{unit}, {_pct(s['g12'])} YoY "
            f"(last 3 periods {_pct(s['g3'])} YoY), "
            f"{'up' if s['streak'] > 0 else 'down' if s['streak'] < 0 else 'flat'} "
            f"{_periods(s['streak'])} running.")
        sh = s.get("shift")
        if sh:
            line += (f" Stepped {'down' if sh['rel_change'] < 0 else 'up'} {_pct(sh['rel_change'])} "
                     f"about {_periods(sh['periods_ago'])} ago (level {sh['from_level']:.0f} -> {sh['to_level']:.0f}).")
        lines.append(line)
    return lines


def _trust_facts(question):
    """Forecast-trust intelligence: how much to rely on each SKU's forecast, from
    history depth + demand regularity. Lets the assistant be honest about
    confidence (and answer 'which forecasts shouldn't I trust?')."""
    try:
        t = catalog_trust()
    except Exception:  # noqa: BLE001
        return []
    skus = t.get("skus", [])
    if not skus:
        return []
    lines = ["Forecast trust (0-100: how reliable each SKU's forecast is, from history "
             "depth + demand regularity; higher = more dependable):"]
    lt = least_trusted(skus, max_level="low", limit=5)
    if lt:
        lines.append("  Least trustworthy (treat with caution): " + "; ".join(
            f"{r['name']} ({r['score']}/100 - {r['reasons'][0]})" for r in lt))
    seen = set()
    named = [s for s in skus if _mentions(s["name"], question)
             and not (s["name"] in seen or seen.add(s["name"]))][:3]
    for s in named:
        lines.append(f"  Trust for {s['name']}: {s['level']} ({s['score']}/100) — "
                     f"{', '.join(s['reasons'])}.")
    return lines if len(lines) > 1 else []


def _facts_from_snapshot(snap):
    """Render the frontend's computed snapshot as labeled fact lines - the only
    numbers the model is allowed to use."""
    lines = []
    b = snap.get("business") or {}
    if b:
        lines.append(
            f"Business: {b.get('products')} products, sales {b.get('span')}, "
            f"forecasting {b.get('grain')}."
        )

    a = snap.get("attention") or {}
    if a:
        lines.append(
            f"Needs attention right now: {a.get('total', 0)} products "
            f"({a.get('stockout', 0)} stockout risk, {a.get('overdue', 0)} overdue deliveries, "
            f"{a.get('demand_shift', 0)} demand shifts, {a.get('overstock', 0)} overstocked)."
        )
        for t in (a.get("top") or [])[:5]:
            lines.append(f"  - {t}")

    p = snap.get("plan") or {}
    if p:
        lines.append(
            f"Plan: forecast demand {p.get('forecast_demand')} units over the horizon; "
            f"suggested order now {p.get('suggested_order')} units at {p.get('service_level')} service; "
            f"{p.get('reorder_now')} products need reorder now; "
            f"fully restocking the catalog costs ${p.get('full_restock_cost')} "
            f"(expected service {p.get('expected_service_full')})."
        )

    tr = snap.get("track_record") or {}
    if tr:
        parts = []
        if tr.get("typical_miss") is not None:
            parts.append(f"typical miss {tr.get('typical_miss')}")
        if tr.get("reconciled"):
            parts.append(f"{tr.get('reconciled')} forecasts graded against real sales")
        if tr.get("realized_coverage") is not None:
            parts.append(f"reality landed inside the stated range {tr.get('realized_coverage')} of the time")
        if tr.get("biased_skus"):
            parts.append(f"{tr.get('biased_skus')} products flagged as running consistently high or low")
        if parts:
            lines.append("Track record: " + "; ".join(parts) + ".")

    bs = snap.get("budget_scenario")
    if bs:
        lines.append(
            f"Budget scenario: with ${bs.get('budget')}, the app would spend ${bs.get('allocated')} "
            f"covering {bs.get('coverage')} of a full restock at {bs.get('expected_service')} expected "
            f"service ({bs.get('funded')} products fully funded, {bs.get('partial')} partial, "
            f"{bs.get('skipped')} skipped)."
        )

    for pr in (snap.get("products") or [])[:4]:
        seg = [f"{pr.get('name')}" + (f" ({pr.get('sku')})" if pr.get('sku') else "")]
        if pr.get("category"):
            seg.append(f"category {pr['category']}")
        if pr.get("forecast") is not None:
            seg.append(f"forecast {pr['forecast']} units")
        if pr.get("yoy") is not None:
            seg.append(f"{pr['yoy']} vs last year")
        if pr.get("on_hand") is not None:
            seg.append(f"{pr['on_hand']} on hand")
        if pr.get("cover_days") is not None:
            seg.append(f"{pr['cover_days']} days of cover")
        if pr.get("suggested_order") is not None:
            seg.append(f"suggested order {pr['suggested_order']}")
        if pr.get("reorder_now"):
            seg.append("flagged reorder-now")
        if pr.get("lead_time") is not None:
            seg.append(f"lead time {pr['lead_time']} days")
        lines.append("Product — " + ", ".join(seg) + ".")

    return "\n".join(lines)


def answer(question, snapshot, history=None):
    """Answer a question grounded ONLY in the snapshot's facts. Returns
    (answer_text, unverified) where unverified flags numbers not traceable to the
    facts (the caller can show a caveat)."""
    snapshot_facts = _facts_from_snapshot(snapshot or {})
    trend_lines = _trend_facts(question)
    trust_lines = _trust_facts(question)
    facts = "\n".join(
        ([snapshot_facts] if snapshot_facts.strip() else []) + trend_lines + trust_lines)
    if not facts.strip():
        return (
            "I don't have any sales data to look at yet — import a catalog and run a "
            "forecast, then ask me again.",
            False,
        )

    context = ""
    for turn in (history or [])[-2:]:
        role = "You" if turn.get("role") == "user" else "Assistant"
        context += f"{role}: {turn.get('content', '')}\n"

    prompt = f"""Answer the question using ONLY the facts below. Never introduce a
number that isn't in the facts. If the facts don't answer it, say what you'd need.

Don't just recite the facts - reason over them like an analyst: lead with what
matters most, call out the non-obvious (a sustained drift, an acceleration, a
category quietly moving), distinguish a lasting trend from a one-off, and end with
what to do next. Be concise and direct (2-5 sentences).

Facts:
{facts}

{("Recent conversation:\n" + context) if context else ""}Question: {question}
"""
    messages = [
        {"role": "system", "content": "You are Insighta, a sharp, data-grounded inventory analyst for a small seller. Use only the figures provided; never invent numbers. Prioritize and explain; don't just list. /no_think"},
        {"role": "user", "content": prompt},
    ]

    best = None
    for _ in range(2):
        text = _chat(messages, max_tokens=260, temperature=0.3, top_p=0.9)
        unsupported = _unsupported_numbers(text, facts)
        if not unsupported:
            return text, False
        if best is None or len(unsupported) < len(best[1]):
            best = (text, unsupported)
    return best[0], True


def briefing(snapshot=None):
    """Proactive 'here's what matters today': the client's attention counts (if a
    forecast has been run) plus the deterministic trend/trust selection. Rendered
    DETERMINISTICALLY - no LLM - because the items are already fully computed, so
    the Assistant opens instantly and needs no model resident. Returns (text,
    items); the client renders the items as a list, with text as a fallback."""
    from app.analytics.briefing import catalog_briefing

    attention = (snapshot or {}).get("attention")
    try:
        items = catalog_briefing(attention=attention, limit=5)
    except Exception:  # noqa: BLE001
        items = []
    if not items:
        return ("Nothing urgent — your catalog looks steady. No sharp declines, quiet "
                "drifts, or shaky forecasts stand out right now.", [])
    text = "Here's what matters today: " + "; ".join(
        f"{it['subject']} — {it['detail']}" for it in items) + "."
    return text, items
