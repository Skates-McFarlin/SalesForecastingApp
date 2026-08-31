import os
from pathlib import Path


def _sqlite_db_path():
    """Writable per-user location for the SQLite file.

    Uses LOCALAPPDATA (writable even when installed to Program Files) when
    available, falling back to a local instance/ folder for dev runs.
    """
    base = os.getenv("LOCALAPPDATA")
    data_dir = Path(base) / "Insighta" if base else Path(__file__).resolve().parent.parent / "instance"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "insighta.db"


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "sales_forecasting_app")

    SQLALCHEMY_DATABASE_URI = f"sqlite:///{_sqlite_db_path().as_posix()}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
