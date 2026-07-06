from app.views.home import home_bp
from app.api.prediction_api import prediction_api_bp


def register_blueprints(app):
    app.register_blueprint(home_bp)
    app.register_blueprint(prediction_api_bp, url_prefix="/api/predictions")
