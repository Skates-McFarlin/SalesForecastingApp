import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "sales_forecasting_app")

    # MySQL Database Config
    DB_USER = os.getenv("DB_USER", "root")  # Default MySQL user is 'root'
    DB_PASSWORD = os.getenv("DB_PASSWORD", "")  # Set your MySQL root password
    DB_HOST = os.getenv("DB_HOST", "localhost")  # Running MySQL locally
    DB_PORT = os.getenv("DB_PORT", "3306")  # Default MySQL port
    DB_NAME = os.getenv("DB_NAME", "sales_forecasting_app")  # Your database name

    SQLALCHEMY_DATABASE_URI = (
        f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
