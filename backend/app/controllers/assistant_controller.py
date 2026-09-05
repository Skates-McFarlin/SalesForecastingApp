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
        if pr.get("correction"):
            seg.append(f"adjusted {pr['correction']} from its track record")
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
    facts = _facts_from_snapshot(snapshot or {})
    if not facts.strip():
        return (
            "I don't have a forecast to look at yet — run one from the Forecast or "
            "Attention tab and then ask me again.",
            False,
        )

    context = ""
    for turn in (history or [])[-2:]:
        role = "You" if turn.get("role") == "user" else "Assistant"
        context += f"{role}: {turn.get('content', '')}\n"

    prompt = f"""You are Insighta, an inventory assistant for a small seller. Answer the
question using ONLY the facts below. Never introduce a number that isn't in the
facts. If the facts don't answer it, say what you'd need. Be concise and direct
(2-4 sentences), and when useful say what to do next.

Facts:
{facts}

{("Recent conversation:\n" + context) if context else ""}Question: {question}
"""
    messages = [
        {"role": "system", "content": "You are a concise, data-grounded inventory assistant. Use only the figures provided; never invent numbers."},
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
