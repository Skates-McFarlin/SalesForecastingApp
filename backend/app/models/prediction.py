from app.extensions import db


class Prediction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    file_id = db.Column(db.Integer, db.ForeignKey("file.id"), nullable=True)
    product_name = db.Column(db.String(100), nullable=False, index=True)
    sku = db.Column(db.String(120), nullable=True, index=True)
    duration = db.Column(db.String(120),  nullable=False)
    forecast = db.Column(db.String(120), nullable=False)
    actual_sales = db.Column(db.String(120), nullable=True)
    percent_change = db.Column(db.String(120), nullable=True)
    category = db.Column(db.String(120), nullable=True)
    seasonality = db.Column(db.String(60), nullable=True)
    forecast_low = db.Column(db.String(120), nullable=True)
    forecast_high = db.Column(db.String(120), nullable=True)
    seasonality_note = db.Column(db.Text, nullable=True)
    summary = db.Column(db.Text, nullable=True)
    summary_unverified = db.Column(db.Boolean, nullable=True)
    history_months = db.Column(db.Integer, nullable=True)
    has_data_gap = db.Column(db.Boolean, nullable=True)
    forecast_method = db.Column(db.String(60), nullable=True)
    forecast_model = db.Column(db.String(60), nullable=True)
    extra_context = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())

    def __repr__(self):
        return f"<Prediction {self.product_name}>"
