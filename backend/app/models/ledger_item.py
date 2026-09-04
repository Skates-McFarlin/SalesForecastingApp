from app.extensions import db


class LedgerItem(db.Model):
    """One SKU's recommendation within a forecast run, plus the realized outcome
    once it's known.

    Written when the run is recorded (the decision); `actual` is filled in later,
    once real sales cover the run's forecast window (the outcome). Kept as an
    immutable snapshot - it records what was recommended *at the time*, so a later
    catalog change never rewrites history the ledger is meant to preserve.
    """
    id = db.Column(db.Integer, primary_key=True)
    run_id = db.Column(
        db.Integer, db.ForeignKey("forecast_run.id"), nullable=False, index=True
    )
    # The catalog's canonical identity (SKU when present, else name) - how the
    # forecaster groups series, so reconciliation can find this product's sales.
    product_key = db.Column(db.String(200), nullable=False, index=True)
    product_name = db.Column(db.String(200), nullable=False)
    sku = db.Column(db.String(120), nullable=True)

    forecast = db.Column(db.Float, nullable=False)          # point forecast, summed
    forecast_low = db.Column(db.Float, nullable=True)       # ~80% band, summed
    forecast_high = db.Column(db.Float, nullable=True)
    recommended_order = db.Column(db.Float, nullable=True)  # forecast + safety stock
    safety_stock = db.Column(db.Float, nullable=True)

    actual = db.Column(db.Float, nullable=True)             # realized sales in window
    reconciled = db.Column(db.Boolean, nullable=False, default=False)

    def __repr__(self):
        return f"<LedgerItem run{self.run_id} {self.product_key} f={self.forecast}>"
