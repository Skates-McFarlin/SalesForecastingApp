from flask import Blueprint, jsonify
from app.controllers.prediction_controller import model_status

health_bp = Blueprint("health", __name__)


@health_bp.route("/api/health")
def health():
    return jsonify(model_status)
