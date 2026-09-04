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
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())
    updated_at = db.Column(
        db.DateTime,
        default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp(),
    )

    sales = db.relationship(
        "SalesRecord", backref="product", cascade="all, delete-orphan", lazy="dynamic"
    )

    def __repr__(self):
        return f"<Product {self.key}>"
