from app.extensions import db


class SalesRecord(db.Model):
    """Actual sales for a product on a given date - stored date-granular so the
    catalog is daily-capable from the start.

    `date` is a real calendar date: daily where the source provides it (e.g. a
    Shopify feed), or the period start for coarser feeds (a monthly spreadsheet
    stores one row per month dated to the 1st). The forecasting layer resamples
    these to whatever grain it works at (weekly rate for operations), and the
    decision layer sums over each SKU's lead-time window in days.

    The unique (product_id, date) constraint means re-syncing an overlapping
    window updates the existing rows rather than duplicating them - the basis for
    incremental "sync since last time" instead of re-uploading everything.
    """
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(
        db.Integer, db.ForeignKey("product.id"), nullable=False, index=True
    )
    date = db.Column(db.Date, nullable=False, index=True)
    quantity = db.Column(db.Float, nullable=False, default=0.0)
    unit_price = db.Column(db.Float, nullable=True)

    __table_args__ = (
        db.UniqueConstraint("product_id", "date", name="uq_sales_product_date"),
    )

    def __repr__(self):
        return f"<SalesRecord p{self.product_id} {self.date} q={self.quantity}>"
