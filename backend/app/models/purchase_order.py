from app.extensions import db


class PurchaseOrder(db.Model):
    """A replenishment order for one product (Phase 2.5).

    This is what makes "what's on the way" and "how long resupply takes" real
    rather than hand-kept: an open PO (received_on is null) counts toward the
    product's on-order position; receiving it moves the units into on-hand. And
    every received PO is one observation of actual lead time (received_on -
    placed_on), so the app can LEARN a product's lead time from its history
    instead of trusting a typed estimate.
    """
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(
        db.Integer, db.ForeignKey("product.id"), nullable=False, index=True
    )
    quantity = db.Column(db.Float, nullable=False)          # units ordered
    placed_on = db.Column(db.Date, nullable=False)          # order date
    expected_on = db.Column(db.Date, nullable=True)         # placed + lead estimate
    received_on = db.Column(db.Date, nullable=True)         # null => still in transit
    received_qty = db.Column(db.Float, nullable=True)       # actual received
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())

    @property
    def is_open(self):
        return self.received_on is None

    def __repr__(self):
        state = "open" if self.is_open else f"received {self.received_on}"
        return f"<PurchaseOrder p{self.product_id} q={self.quantity} {state}>"
