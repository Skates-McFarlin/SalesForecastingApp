from flask import Blueprint, jsonify, request

from app.controllers.purchase_order_controller import create_po, receive_po, cancel_po

purchase_order_api_bp = Blueprint("purchase_order_api", __name__)


@purchase_order_api_bp.route("", methods=["POST"])
@purchase_order_api_bp.route("/", methods=["POST"])
def post_po():
    """Place a replenishment order for a product. Returns the product's refreshed
    inventory state so the UI can update on-order immediately."""
    try:
        body = request.get_json(silent=True) or {}
        key = body.get("product_key")
        qty = body.get("quantity")
        if not key or qty is None:
            return jsonify({"error": "Missing product_key or quantity"}), 400
        state = create_po(key, qty, placed_on=body.get("placed_on"))
        if state is None:
            return jsonify({"error": "Product not found or invalid quantity"}), 400
        return jsonify(state), 201
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)}), 500


@purchase_order_api_bp.route("/<int:po_id>/receive", methods=["POST"])
def receive_po_route(po_id):
    """Receive an open PO (records the arrival + moves units into on-hand)."""
    try:
        body = request.get_json(silent=True) or {}
        state = receive_po(po_id, received_on=body.get("received_on"),
                           received_qty=body.get("received_qty"))
        if state is None:
            return jsonify({"error": "PO not found or already received"}), 404
        return jsonify(state), 200
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)}), 500


@purchase_order_api_bp.route("/<int:po_id>", methods=["DELETE"])
def cancel_po_route(po_id):
    """Cancel an open PO."""
    try:
        state = cancel_po(po_id)
        if state is None:
            return jsonify({"error": "PO not found or already received"}), 404
        return jsonify(state), 200
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)}), 500
