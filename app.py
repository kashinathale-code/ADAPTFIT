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

    from backend.routes import get_configured_badge_info

    @app.context_processor
    def inject_header_badge():
        badge_info = get_configured_badge_info(app.config)
        return {
            "header_badge_text": badge_info["text"],
            "header_badge_class": badge_info["badge_class"],
            "header_badge_is_live": badge_info["is_live"],
        }

    def get_seed_adaptation_data():
        try:
            p = app.config.get("DATABASE_PATH", Config.DATABASE_PATH)
            conn = sqlite3.connect(p, timeout=30.0)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT id, name, description, evidence_source FROM adaptations WHERE id='rain_garden'")
            adapt = cur.fetchone()
            cur.execute("SELECT factor, min_value, max_value, unit, weight, is_critical FROM adaptation_requirements WHERE adaptation_id='rain_garden' ORDER BY id ASC")
            req_rows = cur.fetchall()
            conn.close()
            from backend.compatibility_engine import Requirement, _requirement_summary
            thresholds = {}
            for r in req_rows:
                req_obj = Requirement(
                    factor=r["factor"],
                    min_value=r["min_value"],
                    max_value=r["max_value"],
                    unit=r["unit"] or "",
                    is_critical=bool(r["is_critical"]),
                )
                summ = _requirement_summary(req_obj)
                thresholds[r["factor"]] = f"{summ} (critical)" if r["is_critical"] else summ
            return dict(adapt) if adapt else {}, thresholds
        except Exception:
            return {}, {}

    @app.route("/")
    def index():
        """Dashboard page."""
        adapt, thresholds = get_seed_adaptation_data()
        max_missing_pct = int(round(float(app.config.get("MAX_MISSING_WEIGHT", Config.MAX_MISSING_WEIGHT)) * 100))
        suitable_min = float(app.config.get("SUITABLE_MIN", Config.SUITABLE_MIN))
        return render_template(
            "index.html",
            adaptation=adapt,
            thresholds=thresholds,
            max_missing_pct=max_missing_pct,
            suitable_min=suitable_min,
        )

    @app.route("/new")
    def new_assessment_page():
        """New Assessment page with Leaflet map and preview table."""
        adapt, thresholds = get_seed_adaptation_data()
        max_missing_pct = int(round(float(app.config.get("MAX_MISSING_WEIGHT", Config.MAX_MISSING_WEIGHT)) * 100))
        suitable_min = float(app.config.get("SUITABLE_MIN", Config.SUITABLE_MIN))
        return render_template(
            "assessment.html",
            adaptation=adapt,
            thresholds=thresholds,
            max_missing_pct=max_missing_pct,
            suitable_min=suitable_min,
        )

    @app.route("/results")
    @app.route("/results/<int:assessment_id>")
    def results_page(assessment_id: Optional[int] = None):
        """Assessment Results page."""
        return render_template("results.html", assessment_id=assessment_id)

    @app.route("/history")
    def history_page():
        """Assessment History page."""
        return render_template("history.html")

    @app.route("/compare")
    def compare_page():
        """Compare multiple target locations against reference site (FR-11)."""
        adapt, thresholds = get_seed_adaptation_data()
        max_missing_pct = int(round(float(app.config.get("MAX_MISSING_WEIGHT", Config.MAX_MISSING_WEIGHT)) * 100))
        suitable_min = float(app.config.get("SUITABLE_MIN", Config.SUITABLE_MIN))
        return render_template(
            "compare.html",
            adaptation=adapt,
            thresholds=thresholds,
            max_missing_pct=max_missing_pct,
            suitable_min=suitable_min,
        )

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=Config.DEBUG)
