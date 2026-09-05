from flask import Blueprint, jsonify

from app.controllers.ledger_controller import list_runs, run_detail
from app.controllers.learning_controller import learning_summary

ledger_api_bp = Blueprint("ledger_api", __name__)


@ledger_api_bp.route("/learning", methods=["GET"])
def get_learning():
    """Closed-loop summary (Phase 5): how many SKUs the app has learned
    corrections for, from how many reconciled forecasts."""
    try:
        return jsonify(learning_summary()), 200
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)}), 500


@ledger_api_bp.route("", methods=["GET"])
@ledger_api_bp.route("/", methods=["GET"])
def get_runs():
    """Every recorded forecast run, newest first, with accuracy where reconciled.

    Reconciles pending runs first, so the track record is always current.
    """
    try:
        return jsonify(list_runs()), 200
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)}), 500


@ledger_api_bp.route("/<int:run_id>", methods=["GET"])
def get_run(run_id):
    """Per-SKU forecast-vs-outcome detail for one run."""
    try:
        detail = run_detail(run_id)
        if detail is None:
            return jsonify({"error": "Run not found"}), 404
        return jsonify(detail), 200
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)}), 500
