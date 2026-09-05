"""Purchase orders & learned lead time - Phase 2.5.

Makes "what's on the way" and "how long resupply takes" real instead of
hand-kept. An open PO counts toward on-order; receiving it moves the units into
on-hand. Received POs are observations of actual lead time, so a product's lead
time is LEARNED (median of recent order->arrival gaps) once there's history,
falling back to the typed value and then the business default.
"""
import statistics
from datetime import date, datetime

from app.extensions import db
from app.models.product import Product
from app.models.purchase_order import PurchaseOrder

# Minimum received orders before we trust a learned lead time over the typed one.
MIN_LEAD_OBS = 2
# Only the most recent orders inform the learned lead (suppliers change).
LEAD_WINDOW = 10


def _product(key):
    return Product.query.filter_by(key=key).first()


def _parse_date(value, default=None):
    if not value:
        return default
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


def po_summary(product):
    """PO-derived inventory facts for one product: on-order (sum of open POs),
    the open POs themselves, and the learned lead time (median of recent received
    orders, or None with the count so far). Consumed by inventory_state()."""
    pos = product.purchase_orders.all()
    open_pos = [p for p in pos if p.received_on is None]
    on_order = sum(p.quantity for p in open_pos)

    received = sorted(
        (p for p in pos if p.received_on is not None),
        key=lambda p: p.received_on, reverse=True,
    )[:LEAD_WINDOW]
    gaps = [(p.received_on - p.placed_on).days for p in received if p.received_on >= p.placed_on]
    lead_learned = int(round(statistics.median(gaps))) if len(gaps) >= MIN_LEAD_OBS else None

    return {
        "OnOrder": on_order,
        "LeadLearned": lead_learned,
        "LeadObs": len(gaps),
        "OpenPOs": [
            {
                "id": p.id,
                "quantity": p.quantity,
                "placed_on": p.placed_on.isoformat(),
                "expected_on": p.expected_on.isoformat() if p.expected_on else None,
            }
            for p in sorted(open_pos, key=lambda p: p.placed_on)
        ],
    }


def create_po(product_key, quantity, placed_on=None, lead_time_days=None):
    """Place a replenishment order. expected_on = placed_on + the lead time we'd
    use for this product (learned/typed/default), for display. Returns the
    product's refreshed inventory state (so the UI reflects the new on-order)."""
    from app.controllers.inventory_controller import inventory_state, effective_lead

    product = _product(product_key)
    if product is None:
        return None
    try:
        qty = float(quantity)
    except (TypeError, ValueError):
        return None
    if qty <= 0:
        return None

    placed = _parse_date(placed_on, date.today())
    lead = lead_time_days if lead_time_days is not None else effective_lead(product)
    from datetime import timedelta
    expected = placed + timedelta(days=int(lead)) if lead else None

    po = PurchaseOrder(product_id=product.id, quantity=qty, placed_on=placed, expected_on=expected)
    db.session.add(po)
    db.session.commit()
    return inventory_state(product)


def receive_po(po_id, received_on=None, received_qty=None):
    """Receive an open PO: record the arrival (an actual lead-time observation)
    and move the units into on-hand. Returns the product's refreshed state."""
    from app.controllers.inventory_controller import inventory_state

    po = PurchaseOrder.query.get(po_id)
    if po is None or po.received_on is not None:
        return None
    product = Product.query.get(po.product_id)

    qty = po.quantity
    if received_qty is not None:
        try:
            qty = float(received_qty)
        except (TypeError, ValueError):
            qty = po.quantity
    po.received_on = _parse_date(received_on, date.today())
    po.received_qty = qty
    product.on_hand = float(product.on_hand or 0.0) + qty
    product.inventory_updated_at = datetime.utcnow()
    db.session.commit()
    return inventory_state(product)


def cancel_po(po_id):
    """Cancel an open PO (a mistake or a supplier cancellation). Received POs are
    history and cannot be cancelled. Returns the product's refreshed state."""
    from app.controllers.inventory_controller import inventory_state

    po = PurchaseOrder.query.get(po_id)
    if po is None or po.received_on is not None:
        return None
    product = Product.query.get(po.product_id)
    db.session.delete(po)
    db.session.commit()
    return inventory_state(product)
