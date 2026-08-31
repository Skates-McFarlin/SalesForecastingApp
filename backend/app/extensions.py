import os
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_cors import CORS

db = SQLAlchemy()
migrate = Migrate()
cors = CORS()

MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "migrations")


def init_extensions(app):
    db.init_app(app)
    migrate.init_app(app, db, directory=MIGRATIONS_DIR)
    cors.init_app(app, resources={r"/api/*": {"origins": "*"}})
