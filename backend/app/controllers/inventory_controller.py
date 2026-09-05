"""Inventory state & economics - Phase 2.

Turns a forecast into a grounded reorder decision: knowing what's on hand, what's
already on order, how long resupply takes, and the target service level, the app
computes a reorder point and an order-up-to level and recommends an order that
accounts for the stock you already have.

The reorder POLICY lives here (canonical, used by the simulator's validation and
available server-side); the UI mirrors the same formula client-side so editing
on-hand / lead time / service level updates the recommendation instantly without
re-forecasting. Keep the two in lock-step - see reorder_policy() below.
"""
import math
from datetime import datetime

from app.extensions import db
from app.models.product import Product
from app.models.settings import Settings

# z-multiplier per service level (probability of not stocking out) - matches the
# UI's SERVICE_LEVELS so the number the user sees is the number stored.
SERVICE_Z = {0.9: 1.2816, 0.95: 1.6449, 0.99: 2.3263}


def get_settings():
    """The business-level defaults row, created with sensible defaults on first
    use (single row, id=1)."""
    s = Settings.query.get(1)
    if s is None:
        s = Settings(
            id=1, default_lead_time_days=14, review_period_days=7,
            service_level=0.95, holding_cost_rate=0.25,
        )
        db.session.add(s)
        db.session.commit()
    return s


def update_settings(data):
    s = get_settings()
    for field in ("default_lead_time_days", "review_period_days",
                  "service_level", "holding_cost_rate"):
        if field in data and data[field] is not None:
            setattr(s, field, data[field])
    db.session.commit()
    return s.to_dict()


def inventory_state(product):
    """The inventory fields for one product, in the shape the forecast results
    and the UI use (capitalized keys to sit alongside the forecast fields).

    On-order and learned lead time come from purchase orders (Phase 2.5), so
    "what's on the way" is the sum of open POs rather than a hand-kept number."""
    from app.controllers.purchase_order_controller import po_summary

    state = {
        "OnHand": product.on_hand,
        "LeadTimeDays": product.lead_time_days,  # the typed/planned lead (fallback)
        "UnitCost": product.unit_cost,
        "MOQ": product.moq,
        "CasePack": product.case_pack,
        "InventoryUpdatedAt": (
            product.inventory_updated_at.isoformat() if product.inventory_updated_at else None
        ),
    }
    state.update(po_summary(product))  # OnOrder, LeadLearned, LeadObs, OpenPOs
    return state


def effective_lead(product):
    """The lead time to actually use: learned from received POs when there's
    enough history, else the typed value, else the business default."""
    from app.controllers.purchase_order_controller import po_summary

    learned = po_summary(product).get("LeadLearned")
    if learned is not None:
        return learned
    if product.lead_time_days:
        return product.lead_time_days
    return get_settings().default_lead_time_days


def inventory_by_key():
    """{product.key: inventory_state} for the whole catalog - merged into forecast
    results so the client can compute the grounded order per SKU."""
    return {p.key: inventory_state(p) for p in Product.query.all()}


# on_order is no longer edited by hand - it's derived from open purchase orders.
_INV_FIELDS = ("on_hand", "lead_time_days", "unit_cost", "moq", "case_pack")


def update_product_inventory(key, data):
    """Patch one product's inventory fields (from a UI edit). Stamps
    inventory_updated_at whenever on_hand is set, so the UI can show how fresh the
    position is (on-hand goes stale between syncs)."""
    product = Product.query.filter_by(key=key).first()
    if product is None:
        return None
    for field in _INV_FIELDS:
        if field in data:
            value = data[field]
            setattr(product, field, value if value != "" else None)
    if "on_hand" in data:
        product.inventory_updated_at = datetime.utcnow()
    db.session.commit()
    return inventory_state(product)


def snap_order(qty, moq=None, case_pack=None):
    """Round a raw order up to the case pack, then up to the minimum order
    quantity - the real-world ordering constraints."""
    if qty <= 0:
        return 0.0
    if case_pack and case_pack > 0:
        qty = math.ceil(qty / case_pack) * case_pack
    if moq and qty < moq:
        qty = moq
        if case_pack and case_pack > 0:
            qty = math.ceil(qty / case_pack) * case_pack
    return float(qty)


def reorder_policy(daily_rate, daily_sigma, on_hand, on_order,
                   lead_time_days, review_period_days, z,
                   moq=None, case_pack=None):
    """Periodic-review base-stock policy. Returns the reorder decision.

    Protection interval P = lead time + review period (you must survive on what
    you order until the NEXT order arrives). Demand over P is r*P with spread
    z*sigma*sqrt(P); order up to that level, net of what you already have and
    have coming. The reorder point (for the "order now" flag) is the lead-time
    demand plus its safety. daily_rate/daily_sigma come from the forecast.
    """
    r = max(0.0, float(daily_rate or 0.0))
    s = max(0.0, float(daily_sigma or 0.0))
    L = max(0, int(lead_time_days or 0))
    R = max(1, int(review_period_days or 1))
    P = L + R
    position = float(on_hand or 0.0) + float(on_order or 0.0)

    mu_P = r * P
    safety = z * s * math.sqrt(P)
    order_up_to = mu_P + safety
    reorder_point = r * L + z * s * math.sqrt(L)

    raw_order = max(0.0, order_up_to - position)
    order = snap_order(raw_order, moq, case_pack)
    cover_days = (float(on_hand) / r) if (r > 0 and on_hand is not None) else None

    return {
        "daily_rate": r,
        "order_up_to": order_up_to,
        "reorder_point": reorder_point,
        "safety_stock": safety,
        "suggested_order": order,
        "reorder_now": position <= reorder_point,
        "position": position,
        "cover_days": cover_days,
    }
