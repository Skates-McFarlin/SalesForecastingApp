import os
import pandas as pd
from flask import Blueprint, jsonify, request
from app.controllers.prediction_controller import (
    predict_sales_forecasting,
    calculate_error_metrics,
    get_or_generate_summary,
    inspect_data,
)
from app.models.prediction import Prediction
import json

prediction_api_bp = Blueprint("prediction_api", __name__)


@prediction_api_bp.route("/generate", methods=["POST"])
def generate():
    try:
        if "file" not in request.files:
            return jsonify({"error": "No file part"}), 400

        file = request.files["file"]

        if file.filename == "":
            return jsonify({"error": "No selected file"}), 400

        start_date = request.form.get("start_date")
        duration = request.form.get("duration")

        if not start_date or not duration:
            return jsonify({"error": "Missing start_date or duration"}), 400

        try:
            duration = int(duration)
        except ValueError:
            return jsonify({"error": "Duration must be an integer"}), 400

        return jsonify(json.loads(predict_sales_forecasting(file, start_date, duration))), 201
        

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@prediction_api_bp.route("/inspect", methods=["POST"])
def inspect():
    """Report the month span of an uploaded file so the UI can build its
    start-date pickers from real coverage. Best-effort: any failure just yields
    an empty range and the UI falls back to its default years."""
    try:
        if "file" not in request.files or request.files["file"].filename == "":
            return jsonify({"error": "No file"}), 400
        return jsonify({"range": inspect_data(request.files["file"])}), 200
    except Exception as e:
        return jsonify({"error": str(e), "range": None}), 200


@prediction_api_bp.route("/error_metrics", methods=["POST"])
def error_metrics():
    try:
        if "file" not in request.files:
            return jsonify({"error": "No file part"}), 400

        file = request.files["file"]

        if file.filename == "":
            return jsonify({"error": "No selected file"}), 400

        start_date = request.form.get("start_date")
        duration = request.form.get("duration")

        if not start_date or not duration:
            return jsonify({"error": "Missing start_date or duration"}), 400

        try:
            duration = int(duration)
        except ValueError:
            return jsonify({"error": "Duration must be an integer"}), 400

        return jsonify(json.loads(calculate_error_metrics(file, start_date, duration))), 201


    except Exception as e:
        return jsonify({"error": str(e)}), 500


@prediction_api_bp.route("/<int:prediction_id>/summary", methods=["GET"])
def get_summary(prediction_id):
    try:
        prediction = Prediction.query.get(prediction_id)
        if prediction is None:
            return jsonify({"error": "Prediction not found"}), 404

        summary, unverified = get_or_generate_summary(prediction)
        return jsonify({"Summary": summary, "Unverified": unverified}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

