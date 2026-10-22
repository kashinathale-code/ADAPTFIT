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

from flask import Flask, jsonify, render_template

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

    # Ensure database exists and is seeded on startup if missing or uninitialized
    db_path = app.config.get("DATABASE_PATH", Config.DATABASE_PATH)
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    if not os.path.exists(db_path):
        app.logger.info("Database file not found at %s. Auto-seeding database on startup...", db_path)
        seed(db_path=db_path)
    else:
        # Validate that adaptations table is present
        conn = sqlite3.connect(db_path, timeout=30.0)
        conn.execute("PRAGMA busy_timeout = 30000")
        cur = conn.cursor()
        cur.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='adaptations'"
        )
        has_table = cur.fetchone()[0] > 0
        conn.close()
        if not has_table:
            app.logger.info("Database at %s lacks required schema. Auto-seeding database on startup...", db_path)
            seed(db_path=db_path, force=True)

    # Register blueprints
    app.register_blueprint(api_bp)

    @app.route("/")
    def index():
        """Dashboard page."""
        return render_template("index.html")

    @app.route("/new")
    def new_assessment_page():
        """New Assessment page with Leaflet map and preview table."""
        return render_template("assessment.html")

    @app.route("/results")
    @app.route("/results/<int:assessment_id>")
    def results_page(assessment_id: Optional[int] = None):
        """Assessment Results page."""
        return render_template("results.html", assessment_id=assessment_id)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=Config.DEBUG)
