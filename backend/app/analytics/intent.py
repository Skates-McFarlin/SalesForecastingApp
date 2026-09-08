"""Intent routing for the assistant.

The query space of a small-seller inventory assistant is small and repetitive:
"what needs me?", "what's growing?", "did anything change?", "can I trust this
forecast?", "what should I reorder?". A 1.7B model writing free-form over a dump
of every fact has to do the UNDERSTANDING itself and fails silently when it drifts.

So understanding is deterministic here: a keyword+entity classifier picks one of a
fixed set of intents, the caller assembles only the facts that intent needs, and
the model just phrases them. When nothing matches, we say so VISIBLY (a
capabilities reply) instead of inventing an answer. This is pure and testable - the
smartness is measurable before any model is involved.
"""
import re

# Fine intents -> the keywords that signal them. Substring match (so "trending"
# hits "trend", "declining" hits "declin"). Ordered by SPECIFICITY: earlier intents
# win ties, because a more specific ask ("did it change suddenly") should beat a
# generic one ("how is it doing") when both fire.
INTENTS = [
    ("shift", ["sudden", "abrupt", "out of nowhere", "overnight", "what happened",
               "happened to", "jump", "jumped", "spike", "spiked", "stepped", "step change",
               "changed", "any changes", "did anything change"]),
    ("accuracy", ["accurate", "accuracy", "track record", "how have you done",
                  "how'd you do", "calibrat", "biased", " bias", "been right", "been wrong",
                  "how good are your forecast", "how reliable have you"]),
    ("trust", ["trust", "confidence", "confident", "reliable", "depend on", "shaky",
               "how sure", "believe the", "which forecasts"]),
    ("budget", ["budget", "afford", "only had", "if i had", "if i only", "spend",
                "to work with", "on hand to"]),
    ("reorder", ["reorder", "re-order", "restock", "replenish", "order now",
                 "should i order", "what to order", "should i buy", "buy now", "stock up",
                 "purchase", "what do i order", "run out"]),
    ("forecast", ["forecast", "predict", "projection", "projected", "how many",
                  "how much will i sell", "expect to sell", "demand for", "will i sell"]),
    ("trend", ["trend", "trending", "growing", "grow", "declin", "rising", " rise",
               "falling", " fall", "momentum", "movers", "mover", "slowing", "accelerat",
               "shrink", "best seller", "bestseller", "worst", "picking up", "losing steam",
               "how's the", "doing"]),
    ("attention", ["attention", "urgent", "problem", "issue", "wrong", "worry",
                   "worried", "on fire", "priority", "priorities", "need me", "needs my",
                   "take care", "look at", "concern", "deal with", "focus on"]),
    ("overview", ["overview", "summary", "how's business", "how is business",
                  "how are things", "status", "how am i doing", "tell me about", "state of",
                  "what's up", "brief me", "catch me up"]),
]

# Fine intent -> the fact GROUP the caller assembles for it.
GROUP = {
    "shift": "shift", "accuracy": "accuracy", "trust": "trust",
    "budget": "plan", "reorder": "plan", "forecast": "forecast",
    "trend": "trend", "attention": "attention", "overview": "overview",
    "product": "product", "unknown": "unknown",
}

_AMOUNT = re.compile(r"\$\s?\d|\d[\d,]*\s?(k\b|thousand|dollars|budget)", re.I)


def _tokens(s):
    return set(re.findall(r"[a-z0-9]+", str(s).lower()))


def _mentions(name, qtokens):
    """True if the question references this product/category by a meaningful WHOLE
    word (>=4 chars). Whole-word (not substring) matters: 'order' must not match
    inside 'reorder', or a product named 'Bulk Special Order' hijacks every
    reorder question."""
    return any(len(w) >= 4 and w in qtokens for w in _tokens(name))


def find_entities(question, names):
    """Canonical catalog names (SKUs/categories) referenced in the question, de-
    duped, order-preserved. `names` is the catalog's entity list."""
    qtokens = _tokens(question)
    out, seen = [], set()
    for n in names or []:
        if n and n not in seen and _mentions(n, qtokens):
            out.append(n); seen.add(n)
    return out


def classify(question, names=None):
    """Route a question. Returns {intent, group, entities, has_amount, scores}.

    intent is the fine label; group is the fact bucket the caller fills. A named
    product with no clear ask becomes 'product' (a focused per-SKU summary). No
    keyword and no entity -> 'unknown' (the caller answers with capabilities)."""
    q = f" {(question or '').lower().strip()} "
    entities = find_entities(question, names)
    scores = {}
    for name, kws in INTENTS:
        hits = sum(1 for kw in kws if kw in q)
        if hits:
            scores[name] = hits
    intent = "unknown"
    if scores:
        best = max(scores.values())
        # earliest (most specific) intent among the top scorers
        for name, _ in INTENTS:
            if scores.get(name) == best:
                intent = name
                break
    has_amount = bool(_AMOUNT.search(question or ""))
    if has_amount and intent in ("unknown", "trend", "overview", "forecast"):
        intent = "budget"          # a dollar figure is almost always a budget ask
    if entities and intent in ("unknown", "overview"):
        intent = "product"         # a product named with no ask (or a generic
                                   # "tell me about X") -> summarize that product
    # A bare entity trend question ("how is X") should focus on that SKU, not the
    # whole catalog; the caller keys off `entities` for that.
    return {"intent": intent, "group": GROUP[intent], "entities": entities,
            "has_amount": has_amount, "scores": scores}
