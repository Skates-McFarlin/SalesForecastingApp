from flask import Blueprint, jsonify, request

from app.controllers.assistant_controller import answer

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
        text, unverified = answer(question, body.get("snapshot"), body.get("history"))
        return jsonify({"answer": text, "unverified": unverified}), 200
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)}), 500
