from app.views.home import home_bp
from app.views.health import health_bp
from app.api.prediction_api import prediction_api_bp
from app.api.catalog_api import catalog_api_bp
from app.api.ledger_api import ledger_api_bp
from app.api.inventory_api import inventory_api_bp
from app.api.purchase_order_api import purchase_order_api_bp
from app.api.assistant_api import assistant_api_bp


def register_blueprints(app):
    app.register_blueprint(home_bp)
    app.register_blueprint(health_bp)
    app.register_blueprint(prediction_api_bp, url_prefix="/api/predictions")
    app.register_blueprint(catalog_api_bp, url_prefix="/api/catalog")
    app.register_blueprint(ledger_api_bp, url_prefix="/api/ledger")
    app.register_blueprint(inventory_api_bp, url_prefix="/api/inventory")
    app.register_blueprint(purchase_order_api_bp, url_prefix="/api/purchase-orders")
    app.register_blueprint(assistant_api_bp, url_prefix="/api/assistant")
