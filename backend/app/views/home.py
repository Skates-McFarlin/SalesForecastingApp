from flask import Blueprint, send_from_directory
import os

home_bp = Blueprint(
    "home", __name__, static_folder="../../build", template_folder="../../build"
)


@home_bp.route("/")
@home_bp.route("/<path:path>")
def serve_frontend(path="index.html"):
    build_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../build"))

    if not os.path.exists(os.path.join(build_dir, path)):
        path = "index.html"  # Serve index.html for React routes

    return send_from_directory(build_dir, path)
