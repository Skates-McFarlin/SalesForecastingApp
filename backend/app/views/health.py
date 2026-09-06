from flask import Blueprint, jsonify
from app.controllers.prediction_controller import model_status

health_bp = Blueprint("health", __name__)


@health_bp.route("/api/health")
def health():
    """Backend readiness (for the startup gate) is decoupled from the model: if
    Flask can answer, the app is usable - forecasting, inventory, and the
    (templated) briefing need no model. The LLM loads lazily on the first
    free-form question; its state is reported separately under `model`."""
    return jsonify({
        "ready": True,
        "status": "ready",
        "error": None,
        "model": model_status,
    })
