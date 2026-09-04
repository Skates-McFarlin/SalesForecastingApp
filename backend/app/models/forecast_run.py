from app.extensions import db


class ForecastRun(db.Model):
    """One forecast the app produced over the catalog - the decision half of the
    decision/outcome ledger (Phase 1).

    Each run records what was recommended at the time it was made; reconciliation
    later fills in what actually sold (see LedgerItem.actual), so the app can
    grade its own past forecasts on the user's real business. That accumulating
    record is the fuel the self-correcting loop (Phase 5) will run on - and,
    immediately, an honest track record of accuracy on the user's own data rather
    than a synthetic backtest.
    """
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(
        db.DateTime, default=db.func.current_timestamp(), index=True
    )
    grain = db.Column(db.String(20), nullable=False)        # "monthly" | "weekly"
    start_date = db.Column(db.Date, nullable=False)         # forecast period start
    horizon = db.Column(db.Integer, nullable=False)         # periods forecast
    # The service level the recorded "recommended order" was computed at - the
    # decision of record (the user can still explore other levels live).
    service_level = db.Column(db.Float, nullable=False)
    catalog_products = db.Column(db.Integer, nullable=True)  # catalog size at run time
    catalog_date_to = db.Column(db.Date, nullable=True)      # history end known then
    # "pending" until its forecast window is fully covered by real sales, then
    # "complete" once reconciled against them.
    status = db.Column(db.String(20), nullable=False, default="pending")
    reconciled_at = db.Column(db.DateTime, nullable=True)

    items = db.relationship(
        "LedgerItem", backref="run", cascade="all, delete-orphan", lazy="dynamic"
    )

    def __repr__(self):
        return f"<ForecastRun {self.id} {self.grain} {self.start_date} h{self.horizon}>"
