from flask import Blueprint, jsonify, request

from app.controllers.inventory_controller import (
    get_settings, update_settings, update_product_inventory,
)

inventory_api_bp = Blueprint("inventory_api", __name__)


@inventory_api_bp.route("/settings", methods=["GET"])
def get_settings_route():
    """Business-level inventory defaults (lead time, review period, service
    level, holding-cost rate)."""
    try:
        return jsonify(get_settings().to_dict()), 200
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)}), 500


@inventory_api_bp.route("/settings", methods=["PUT"])
def put_settings_route():
    try:
        body = request.get_json(silent=True) or {}
        return jsonify(update_settings(body)), 200
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)}), 500


@inventory_api_bp.route("/product/<path:key>", methods=["PUT"])
def put_product_inventory(key):
    """Patch one product's inventory state (on-hand, on-order, lead time, cost,
    MOQ, case pack) from a UI edit."""
    try:
        body = request.get_json(silent=True) or {}
        state = update_product_inventory(key, body)
        if state is None:
            return jsonify({"error": "Product not found"}), 404
        return jsonify(state), 200
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)}), 500
