import os
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_cors import CORS
from sqlalchemy import event
from sqlalchemy.engine import Engine

db = SQLAlchemy()
migrate = Migrate()
cors = CORS()

MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "migrations")


@event.listens_for(Engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record):
    """WAL + synchronous=NORMAL trade a small durability window (the last
    commit could be lost on an OS crash, not corrupted) for much cheaper
    commits - a reasonable trade for a local, single-user forecasting tool
    with no concurrent writers to protect against."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


def init_extensions(app):
    db.init_app(app)
    migrate.init_app(app, db, directory=MIGRATIONS_DIR)
    cors.init_app(app, resources={r"/api/*": {"origins": "*"}})
