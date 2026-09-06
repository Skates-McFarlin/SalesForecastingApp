import time

from flask import Blueprint, jsonify, request

from app.controllers.assistant_controller import answer, briefing
from app.controllers.prediction_controller import ensure_model, model_status

assistant_api_bp = Blueprint("assistant_api", __name__)


@assistant_api_bp.route("", methods=["POST"])
@assistant_api_bp.route("/", methods=["POST"])
def ask():
    """Answer a question about the business, grounded in the snapshot of real
    computed figures the client assembled (Phase 6). The LLM only phrases the
    answer; every number comes from the snapshot."""
    try:
        body = request.get_json(silent=True) or {}
        question = (body.get("question") or "").strip()
        if not question:
            return jsonify({"error": "No question"}), 400
        # The model loads lazily on first use. Kick it off and wait briefly (covers
        # the ~seconds load once downloaded); if it's still fetching the one-time
        # ~1GB download, tell the user to retry rather than hang the request.
        ensure_model()
        for _ in range(20):
            if model_status["ready"] or model_status["status"] == "error":
                break
            time.sleep(1)
        if not model_status["ready"]:
            if model_status["status"] == "error":
                msg = f"The assistant model failed to load: {model_status.get('error') or 'unknown error'}."
                return jsonify({"answer": msg, "unverified": False, "model_status": "error"}), 200
            return jsonify({
                "answer": "Warming up the assistant — downloading its model for the first time "
                          "(a one-time ~1GB download). Give it a minute, then ask again.",
                "unverified": False, "model_status": model_status["status"],
            }), 200
        text, unverified = answer(question, body.get("snapshot"), body.get("history"))
        return jsonify({"answer": text, "unverified": unverified}), 200
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)}), 500


@assistant_api_bp.route("/briefing", methods=["POST"])
def brief():
    """Proactive 'here's what matters today' - the assistant's opening lead,
    composed from trends + trust (+ live attention from the snapshot, if any)."""
    try:
        body = request.get_json(silent=True) or {}
        text, items = briefing(body.get("snapshot"))
        return jsonify({"briefing": text, "items": items}), 200
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)}), 500
