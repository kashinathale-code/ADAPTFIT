"""
ADAPTFIT Flask Application Entry Point
======================================
Implements application factory create_app(), database auto-initialization,
and registers all API routes.
"""

from __future__ import annotations

import os
import sqlite3
from typing import Any, Dict, Optional

from flask import Flask, jsonify

from backend.routes import api_bp
from config import Config
from database.seed import seed


def create_app(test_config: Optional[Dict[str, Any]] = None) -> Flask:
    """Create and configure the Flask application."""
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), "frontend", "templates"),
        static_folder=os.path.join(os.path.dirname(__file__), "frontend", "static"),
    )

    # Load defaults from config.py
    app.config.from_object(Config)

    if test_config:
        app.config.update(test_config)

    # Ensure database exists and is seeded
    db_path = app.config.get("DATABASE_PATH", Config.DATABASE_PATH)
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    if not os.path.exists(db_path):
        seed(db_path=db_path)
    else:
        # Validate that adaptations table is present
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='adaptations'"
        )
        has_table = cur.fetchone()[0] > 0
        conn.close()
        if not has_table:
            seed(db_path=db_path, force=True)

    # Register blueprints
    app.register_blueprint(api_bp)

    @app.route("/")
    def index():
        return jsonify(
            {
                "name": "ADAPTFIT API",
                "version": "0.2.0",
                "status": "online",
                "endpoints": [
                    "GET /api/adaptations",
                    "GET /api/location-data?lat=&lon=",
                    "POST /api/assessments",
                    "GET /api/assessments/<id>",
                ],
            }
        )

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=Config.DEBUG)
