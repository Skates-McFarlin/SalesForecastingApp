from flask import Flask
from flask_migrate import upgrade
from app.config import Config
from app.extensions import db, migrate, init_extensions
from app.routes import register_blueprints


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Initialize extensions
    init_extensions(app)

    # Register Blueprints
    register_blueprints(app)

    # Apply any pending migrations automatically (idempotent, no-op once at head)
    with app.app_context():
        upgrade()

    return app
