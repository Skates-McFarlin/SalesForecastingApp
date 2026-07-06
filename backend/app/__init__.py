from flask import Flask
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

    return app
