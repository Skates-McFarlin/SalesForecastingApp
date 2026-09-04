import json

from flask import Blueprint, jsonify, request

from app.controllers.catalog_controller import import_sales, catalog_summary
from app.controllers.prediction_controller import (
    predict_from_catalog,
    calculate_error_metrics_from_catalog,
)

catalog_api_bp = Blueprint("catalog_api", __name__)


@catalog_api_bp.route("", methods=["GET"])
@catalog_api_bp.route("/", methods=["GET"])
def get_catalog():
    """Summary of the stored business - the UI opens onto this."""
    try:
        return jsonify(catalog_summary()), 200
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)}), 500


@catalog_api_bp.route("/import", methods=["POST"])
def post_import():
    """Merge an uploaded sales file into the persistent catalog."""
    try:
        if "file" not in request.files or request.files["file"].filename == "":
            return jsonify({"error": "No file"}), 400
        return jsonify(import_sales(request.files["file"])), 201
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)}), 500


@catalog_api_bp.route("/forecast", methods=["POST"])
def post_forecast():
    """Forecast the stored catalog forward from its data edge (Phase 0c).

    Takes only a horizon (`duration`); the origin is always the catalog's edge
    (see predict_from_catalog), so there's no start date to pick or mis-align.
    """
    try:
        body = request.get_json(silent=True) or request.form
        duration = body.get("duration")
        if not duration:
            return jsonify({"error": "Missing duration"}), 400
        # Optional: report only a specific future window (e.g. just Q4). The full
        # path from the data edge is still forecast to reach it.
        window_start = body.get("window_start") or None
        return jsonify(json.loads(predict_from_catalog(int(duration), window_start))), 201
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)}), 500


@catalog_api_bp.route("/accuracy", methods=["POST"])
def post_accuracy():
    """Backtest accuracy on the stored catalog (Phase 0c)."""
    try:
        body = request.get_json(silent=True) or request.form
        start_date = body.get("start_date")
        duration = body.get("duration")
        if not start_date or not duration:
            return jsonify({"error": "Missing start_date or duration"}), 400
        result = calculate_error_metrics_from_catalog(start_date, int(duration))
        return jsonify(json.loads(result)), 201
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)}), 500
