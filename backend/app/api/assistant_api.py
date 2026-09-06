from flask import Blueprint, jsonify, request

from app.controllers.assistant_controller import answer, briefing

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
