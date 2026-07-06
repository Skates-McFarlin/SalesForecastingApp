from app.extensions import db


class Prediction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    file_id = db.Column(db.Integer, db.ForeignKey("file.id"), nullable=False)
    product_name = db.Column(db.String(100), nullable=False)
    duration = db.Column(db.String(120),  nullable=False)
    forecast = db.Column(db.String(120), nullable=False)
    actual_sales = db.Column(db.String(120), nullable=True)
    percent_change = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())

    def __repr__(self):
        return f"<Prediction {self.product_name}>"
