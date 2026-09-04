from app.extensions import db


class Settings(db.Model):
    """Business-level inventory defaults (Phase 2) - a single row (id=1).

    These are the knobs that apply catalog-wide unless a product overrides them:
    how long resupply takes by default, how often you reorder (the review
    period), the target service level, and the annual cost of holding stock (as a
    fraction of unit cost). Kept as one typed row rather than a key/value bag so
    reads stay simple; get_settings() creates it on first use.
    """
    id = db.Column(db.Integer, primary_key=True)
    default_lead_time_days = db.Column(db.Integer, nullable=False, default=14)
    review_period_days = db.Column(db.Integer, nullable=False, default=7)
    service_level = db.Column(db.Float, nullable=False, default=0.95)
    holding_cost_rate = db.Column(db.Float, nullable=False, default=0.25)  # annual

    def to_dict(self):
        return {
            "default_lead_time_days": self.default_lead_time_days,
            "review_period_days": self.review_period_days,
            "service_level": self.service_level,
            "holding_cost_rate": self.holding_cost_rate,
        }
