from app.extensions import db


class Product(db.Model):
    """A product in the persistent catalog - the stateful heart of the app.

    `key` is the canonical identity (the SKU when the file provides one, else the
    product name), matching how the forecaster groups series. Sales history hangs
    off this via SalesRecord, so the catalog survives between sessions instead of
    being rebuilt from a fresh upload every run.
    """
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(200), nullable=False, unique=True, index=True)
    sku = db.Column(db.String(120), nullable=True, index=True)
    name = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(120), nullable=True)
    attributes = db.Column(db.Text, nullable=True)  # JSON: file extras + LLM tags

    # Inventory state & economics (Phase 2). All nullable - a product with no
    # inventory data falls back to the statistical order until the user fills it
    # in (from the synced file or by editing). on_hand/on_order are point-in-time
    # position; lead_time/unit_cost/moq/case_pack are the reorder parameters.
    on_hand = db.Column(db.Float, nullable=True)          # units in stock now
    on_order = db.Column(db.Float, nullable=True)         # in-transit units
    lead_time_days = db.Column(db.Integer, nullable=True)  # supplier resupply time
    unit_cost = db.Column(db.Float, nullable=True)        # cost per unit
    moq = db.Column(db.Integer, nullable=True)            # minimum order quantity
    case_pack = db.Column(db.Integer, nullable=True)      # order in multiples of
    inventory_updated_at = db.Column(db.DateTime, nullable=True)  # when on_hand was set

    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())
    updated_at = db.Column(
        db.DateTime,
        default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp(),
    )

    sales = db.relationship(
        "SalesRecord", backref="product", cascade="all, delete-orphan", lazy="dynamic"
    )
    purchase_orders = db.relationship(
        "PurchaseOrder", backref="product", cascade="all, delete-orphan", lazy="dynamic"
    )

    def __repr__(self):
        return f"<Product {self.key}>"
