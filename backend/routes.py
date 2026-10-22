"""
ADAPTFIT Flask API Routes
=========================
Implements TRD Section 7:
- GET  /api/adaptations
- GET  /api/location-data?lat=&lon=
- POST /api/assessments
- GET  /api/assessments/<id>
"""

from __future__ import annotations

import io
import os
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from flask import Blueprint, current_app, jsonify, request, send_file

from backend.compatibility_engine import (
    DISCLAIMER,
    EngineConfig,
    Requirement,
    assess,
)
from backend.data_fetcher import (
    FACTOR_KEYS,
    FACTOR_UNITS,
    fetch_location_environmental_data,
    geocode_place,
)
from backend.data_processor import (
    clean_environmental_value,
    generate_metadata_warnings,
    generate_rainfall_grid_warning,
    validate_coordinates,
)
from config import Config

api_bp = Blueprint("api", __name__, url_prefix="/api")

# Human-readable display names for the five assessment factors.
_FACTOR_DISPLAY_NAMES: Dict[str, str] = {
    "annual_rainfall": "rainfall",
    "slope": "slope",
    "soil_infiltration": "soil infiltration",
    "open_space": "open space",
    "building_distance": "building distance",
}


def build_data_badge_label(factors_payload: List[Dict[str, Any]]) -> str:
    """
    Build the header badge label string from the factors payload.

    Each factor's source is classified as:
      - "Live"              when a_source or b_source starts with "Live:"
      - "Estimated (proxy)" when a_source or b_source starts with "Estimated (proxy):"
      - "Demo"              otherwise

    Return value:
      - All factors demo  → "Sample data for demo, not live"
      - Mixed             → e.g. "Live: rainfall, slope | Demo: soil infiltration …"

    This pure function is intentionally free of Flask context so it can be
    exercised directly in unit tests.
    """
    live: List[str] = []
    estimated: List[str] = []
    demo: List[str] = []

    for f in factors_payload:
        key = f.get("factor", "")
        src_a = f.get("a_source") or ""
        src_b = f.get("b_source") or f.get("source") or ""
        name = _FACTOR_DISPLAY_NAMES.get(key, key.replace("_", " "))

        if src_a.startswith("Live:") or src_b.startswith("Live:"):
            live.append(name)
        elif src_a.startswith("Estimated (proxy):") or src_b.startswith("Estimated (proxy):"):
            estimated.append(name)
        else:
            demo.append(name)

    # All-demo shortcut → original static message
    if not live and not estimated:
        return "Sample data for demo, not live"

    parts: List[str] = []
    if live:
        parts.append(f"Live: {', '.join(live)}")
    if estimated:
        parts.append(f"Estimated: {', '.join(estimated)}")
    if demo:
        parts.append(f"Demo: {', '.join(demo)}")
    return " | ".join(parts)


def _get_db_connection() -> sqlite3.Connection:
    """Return a connection to the SQLite database with Row row_factory."""
    db_path = current_app.config.get("DATABASE_PATH", Config.DATABASE_PATH)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# --------------------------------------------------------------------------- #
# GET /api/adaptations                                                        #
# --------------------------------------------------------------------------- #

@api_bp.route("/adaptations", methods=["GET"])
def get_adaptations():
    """List available adaptation interventions from the knowledge base with their criteria."""
    conn = _get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name, description, evidence_source FROM adaptations")
    rows = cur.fetchall()

    cur.execute(
        """
        SELECT adaptation_id, factor, min_value, max_value, unit, weight,
               is_critical, transfer_tolerance, tolerance_type, evidence, rule_version
        FROM adaptation_requirements
        ORDER BY id ASC
        """
    )
    req_rows = cur.fetchall()
    conn.close()

    from backend.compatibility_engine import Requirement, _requirement_summary

    reqs_by_adapt: Dict[str, List[Dict[str, Any]]] = {}
    for r in req_rows:
        req_obj = Requirement(
            factor=r["factor"],
            min_value=r["min_value"],
            max_value=r["max_value"],
            unit=r["unit"] or "",
            is_critical=bool(r["is_critical"]),
        )
        summ = _requirement_summary(req_obj)
        crit_str = " (critical)" if r["is_critical"] else ""
        r_dict = {
            "factor": r["factor"],
            "min_value": r["min_value"],
            "max_value": r["max_value"],
            "unit": r["unit"],
            "weight": r["weight"],
            "is_critical": bool(r["is_critical"]),
            "transfer_tolerance": r["transfer_tolerance"],
            "tolerance_type": r["tolerance_type"],
            "evidence": r["evidence"],
            "rule_version": r["rule_version"],
            "threshold": f"{summ}{crit_str}",
        }
        reqs_by_adapt.setdefault(r["adaptation_id"], []).append(r_dict)

    suitable_min = float(current_app.config.get("SUITABLE_MIN", Config.SUITABLE_MIN))
    max_missing_weight = float(current_app.config.get("MAX_MISSING_WEIGHT", Config.MAX_MISSING_WEIGHT))

    adaptations = [
        {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "evidence_source": row["evidence_source"],
            "requirements": reqs_by_adapt.get(row["id"], []),
            "thresholds": {
                r["factor"]: r["threshold"] for r in reqs_by_adapt.get(row["id"], [])
            },
            "suitable_min": suitable_min,
            "max_missing_weight": max_missing_weight,
        }
        for row in rows
    ]
    return jsonify(adaptations), 200


# --------------------------------------------------------------------------- #
# GET /api/location-data?lat=&lon=                                           #
# --------------------------------------------------------------------------- #

@api_bp.route("/location-data", methods=["GET"])
def get_location_data():
    """Retrieve environmental data and metadata for a given coordinate."""
    lat_param = request.args.get("lat")
    lon_param = request.args.get("lon")
    name_param = request.args.get("name")

    if lat_param is None or lon_param is None:
        return (
            jsonify({"error": "Missing required query parameters: 'lat' and 'lon'."}),
            400,
        )

    try:
        lat, lon = validate_coordinates(lat_param, lon_param)
    except ValueError as err:
        return jsonify({"error": str(err)}), 400

    csv_path = current_app.config.get("SAMPLE_CSV_PATH")
    data = fetch_location_environmental_data(lat, lon, name=name_param, csv_path=csv_path)

    # Format factors map matching TRD expectations
    factors_payload: Dict[str, Any] = {}
    for factor in FACTOR_KEYS:
        val = data["values"].get(factor)
        meta = data["metadata"].get(factor, {})
        factors_payload[factor] = {
            "value": val,
            "unit": meta.get("unit", FACTOR_UNITS.get(factor, "")),
            "source": meta.get("source"),
            "resolution": meta.get("resolution"),
            "data_date": meta.get("data_date"),
        }

    meta_warnings = generate_metadata_warnings(data["metadata"], location_label=data["name"] or "Location")
    all_warnings = list(dict.fromkeys(data["warnings"] + meta_warnings))

    response_payload = {
        "name": data["name"],
        "latitude": data["latitude"],
        "longitude": data["longitude"],
        "matched_sample_location": data.get("matched_sample_location"),
        "distance_km": data.get("distance_km"),
        "factors": factors_payload,
        "data_quality_warnings": all_warnings,
        "live_rainfall_used": data.get("live_rainfall_used", False),
        "live_slope_used": data.get("live_slope_used", False),
        "live_soil_used": data.get("live_soil_used", False),
        "live_osm_used": data.get("live_osm_used", False),
    }
    return jsonify(response_payload), 200


# --------------------------------------------------------------------------- #
# GET /api/geocode?q=...                                                     #
# --------------------------------------------------------------------------- #

@api_bp.route("/geocode", methods=["GET"])
def geocode_endpoint():
    """Geocode a place name using OpenStreetMap Nominatim with caching and rate limiting."""
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"error": "Query parameter 'q' is required."}), 400

    db_path = current_app.config.get("DATABASE_PATH")
    results = geocode_place(query, db_path=db_path)
    return jsonify({"query": query, "results": results}), 200


# --------------------------------------------------------------------------- #
# POST /api/assessments                                                       #
# --------------------------------------------------------------------------- #

def _run_single_assessment(
    conn: sqlite3.Connection,
    adaptation_id: str,
    ref_loc: Dict[str, Any],
    tgt_loc: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], Optional[str], int]:
    """
    Execute a single adaptation compatibility assessment against a database connection.
    Returns (response_dict, error_message, http_status_code).
    """
    # Validate coordinates
    try:
        ref_lat, ref_lon = validate_coordinates(
            ref_loc.get("latitude"), ref_loc.get("longitude")
        )
    except ValueError as err:
        return None, f"Invalid reference_location coordinates: {err}", 400

    try:
        tgt_lat, tgt_lon = validate_coordinates(
            tgt_loc.get("latitude"), tgt_loc.get("longitude")
        )
    except ValueError as err:
        return None, f"Invalid target_location coordinates: {err}", 400

    cur = conn.cursor()

    # Validate adaptation exists (404 if not found)
    cur.execute("SELECT id, name FROM adaptations WHERE id = ?", (adaptation_id,))
    adapt_row = cur.fetchone()
    if not adapt_row:
        return None, f"Unknown adaptation '{adaptation_id}'.", 404

    # Load requirements from SQLite
    cur.execute(
        """
        SELECT factor, min_value, max_value, unit, weight, is_critical,
               transfer_tolerance, tolerance_type, evidence, rule_version
        FROM adaptation_requirements
        WHERE adaptation_id = ?
        """,
        (adaptation_id,),
    )
    req_rows = cur.fetchall()
    if not req_rows:
        return None, f"No requirements defined for adaptation '{adaptation_id}'.", 400

    requirements = [
        Requirement(
            factor=row["factor"],
            min_value=row["min_value"],
            max_value=row["max_value"],
            unit=row["unit"] or "",
            weight=row["weight"],
            is_critical=bool(row["is_critical"]),
            transfer_tolerance=row["transfer_tolerance"],
            tolerance_type=row["tolerance_type"],
            evidence=row["evidence"] or "",
            rule_version=row["rule_version"] or "",
        )
        for row in req_rows
    ]

    csv_path = current_app.config.get("SAMPLE_CSV_PATH")

    # Fetch Location A profile (allow payload factor override)
    ref_name = ref_loc.get("name") or "Location A"
    fetched_a = fetch_location_environmental_data(ref_lat, ref_lon, name=ref_name, csv_path=csv_path)
    profile_a: Dict[str, Optional[float]] = {}
    meta_a: Dict[str, Dict[str, Any]] = {}
    user_factors_a = ref_loc.get("factors") if isinstance(ref_loc.get("factors"), dict) else {}

    for req_item in requirements:
        fk = req_item.factor
        if fk in user_factors_a:
            val = clean_environmental_value(user_factors_a[fk])
        elif fk in ref_loc:
            val = clean_environmental_value(ref_loc[fk])
        else:
            val = fetched_a["values"].get(fk)
        profile_a[fk] = val
        meta_a[fk] = fetched_a["metadata"].get(fk, {})

    # Fetch Location B profile (allow payload factor override)
    tgt_name = tgt_loc.get("name") or "Location B"
    fetched_b = fetch_location_environmental_data(tgt_lat, tgt_lon, name=tgt_name, csv_path=csv_path)
    profile_b: Dict[str, Optional[float]] = {}
    meta_b: Dict[str, Dict[str, Any]] = {}
    user_factors_b = tgt_loc.get("factors") if isinstance(tgt_loc.get("factors"), dict) else {}

    for req_item in requirements:
        fk = req_item.factor
        if fk in user_factors_b:
            val = clean_environmental_value(user_factors_b[fk])
        elif fk in tgt_loc:
            val = clean_environmental_value(tgt_loc[fk])
        else:
            val = fetched_b["values"].get(fk)
        profile_b[fk] = val
        meta_b[fk] = fetched_b["metadata"].get(fk, {})

    # Run compatibility assessment
    cfg = EngineConfig()
    if "SUITABLE_MIN" in current_app.config:
        cfg.SUITABLE_MIN = float(current_app.config["SUITABLE_MIN"])
    if "MAX_MISSING_WEIGHT" in current_app.config:
        cfg.MAX_MISSING_WEIGHT = float(current_app.config["MAX_MISSING_WEIGHT"])

    assessment_res = assess(requirements, profile_a, profile_b, cfg)

    # Collect and deduplicate data quality warnings (engine + source/resolution)
    rainfall_grid_warning = generate_rainfall_grid_warning(
        meta_a.get("annual_rainfall", {}).get("source"),
        meta_b.get("annual_rainfall", {}).get("source"),
    )
    src_res_warnings = (
        fetched_a["warnings"]
        + fetched_b["warnings"]
        + generate_metadata_warnings(meta_a, location_label=ref_name)
        + generate_metadata_warnings(meta_b, location_label=tgt_name)
    )
    if rainfall_grid_warning:
        src_res_warnings.append(rainfall_grid_warning)
    combined_warnings = list(
        dict.fromkeys(assessment_res.data_quality_warnings + src_res_warnings)
    )

    # Save Location records into SQLite
    cur.execute(
        "INSERT INTO locations (name, latitude, longitude) VALUES (?, ?, ?)",
        (ref_name, ref_lat, ref_lon),
    )
    loc_a_id = cur.lastrowid

    cur.execute(
        "INSERT INTO locations (name, latitude, longitude) VALUES (?, ?, ?)",
        (tgt_name, tgt_lat, tgt_lon),
    )
    loc_b_id = cur.lastrowid

    # Save Assessment record into SQLite
    cur.execute(
        """
        INSERT INTO assessments (adaptation_id, location_a_id, location_b_id, status, score)
        VALUES (?, ?, ?, ?, ?)
        """,
        (adaptation_id, loc_a_id, loc_b_id, assessment_res.status, assessment_res.score),
    )
    assessment_id = cur.lastrowid

    # Save Assessment factors into SQLite
    factors_payload: List[Dict[str, Any]] = []
    for fr in assessment_res.factors:
        cur.execute(
            """
            INSERT INTO assessment_factors
                (assessment_id, factor, a_value, b_value, factor_status, interpretation)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                assessment_id,
                fr.factor,
                fr.a_value,
                fr.b_value,
                fr.factor_status,
                fr.interpretation,
            ),
        )

        b_meta = meta_b.get(fr.factor, {})
        a_meta_item = meta_a.get(fr.factor, {})
        factors_payload.append(
            {
                "factor": fr.factor,
                "a_value": fr.a_value,
                "b_value": fr.b_value,
                "requirement": fr.requirement_summary,
                "factor_status": fr.factor_status,
                "transfer_risk": fr.transfer_risk,
                "interpretation": fr.interpretation,
                "source": b_meta.get("source") or "Demo value",
                "resolution": b_meta.get("resolution") or "n/a (demo)",
                "a_source": a_meta_item.get("source") or "Demo value",
                "a_resolution": a_meta_item.get("resolution") or "n/a (demo)",
                "b_source": b_meta.get("source") or "Demo value",
                "b_resolution": b_meta.get("resolution") or "n/a (demo)",
                "evidence": fr.evidence,
                "rule_version": fr.rule_version,
            }
        )

    # Response strictly matching TRD Section 7
    response_body = {
        "assessment_id": assessment_id,
        "adaptation_id": adaptation_id,
        "adaptation_name": adapt_row["name"],
        "reference_location": {
            "name": ref_name,
            "latitude": ref_lat,
            "longitude": ref_lon,
        },
        "target_location": {
            "name": tgt_name,
            "latitude": tgt_lat,
            "longitude": tgt_lon,
        },
        "location_a": {
            "name": ref_name,
            "latitude": ref_lat,
            "longitude": ref_lon,
        },
        "location_b": {
            "name": tgt_name,
            "latitude": tgt_lat,
            "longitude": tgt_lon,
        },
        "status": assessment_res.status,
        "score": round(assessment_res.score, 2) if assessment_res.score is not None else None,
        "suitable_min": cfg.SUITABLE_MIN,
        "max_missing_weight": cfg.MAX_MISSING_WEIGHT,
        "factors": factors_payload,
        "supporting_factors": assessment_res.supporting_factors,
        "limiting_factors": assessment_res.limiting_factors,
        "suggested_checks": assessment_res.suggested_checks,
        "data_quality_warnings": combined_warnings,
        "disclaimer": assessment_res.disclaimer,
        "data_badge_label": build_data_badge_label(factors_payload),
        "live_rainfall_used": bool(
            fetched_a.get("live_rainfall_used")
            or fetched_b.get("live_rainfall_used")
            or any((f.get("factor") == "annual_rainfall" and ((f.get("source") or "").startswith("Live") or (f.get("b_source") or "").startswith("Live") or (f.get("a_source") or "").startswith("Live"))) for f in factors_payload)
        ),
        "live_slope_used": bool(
            fetched_a.get("live_slope_used")
            or fetched_b.get("live_slope_used")
            or any((f.get("factor") == "slope" and ((f.get("source") or "").startswith("Live") or (f.get("b_source") or "").startswith("Live") or (f.get("a_source") or "").startswith("Live"))) for f in factors_payload)
        ),
        "live_soil_used": bool(
            fetched_a.get("live_soil_used")
            or fetched_b.get("live_soil_used")
            or any((f.get("factor") == "soil_infiltration" and ((f.get("source") or "").startswith("Live") or (f.get("b_source") or "").startswith("Live") or (f.get("a_source") or "").startswith("Live"))) for f in factors_payload)
        ),
        "live_osm_used": bool(
            fetched_a.get("live_osm_used")
            or fetched_b.get("live_osm_used")
            or any((f.get("factor") in ("open_space", "building_distance") and ((f.get("source") or "").startswith("Live") or (f.get("b_source") or "").startswith("Live") or (f.get("a_source") or "").startswith("Live"))) for f in factors_payload)
        ),
    }
    return response_body, None, 201


@api_bp.route("/assessments", methods=["POST"])
def create_assessment():
    """Run an adaptation compatibility assessment and save to SQLite."""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Request body must be a valid JSON object."}), 400

    adaptation_id = payload.get("adaptation_id")
    if not adaptation_id or not isinstance(adaptation_id, str):
        return jsonify({"error": "Missing or invalid 'adaptation_id'."}), 400

    ref_loc = payload.get("reference_location")
    tgt_loc = payload.get("target_location")

    if not isinstance(ref_loc, dict) or not isinstance(tgt_loc, dict):
        return (
            jsonify(
                {"error": "'reference_location' and 'target_location' must be objects."}
            ),
            400,
        )

    conn = _get_db_connection()
    try:
        res, err, status_code = _run_single_assessment(conn, adaptation_id, ref_loc, tgt_loc)
        if err:
            conn.close()
            return jsonify({"error": err}), status_code
        conn.commit()
        conn.close()
        return jsonify(res), 201
    except Exception:
        conn.rollback()
        conn.close()
        raise


# --------------------------------------------------------------------------- #
# POST /api/comparisons (FR-11: Compare multiple targets)                      #
# --------------------------------------------------------------------------- #

_STATUS_RANK_ORDER: Dict[str, int] = {
    "suitable": 1,
    "conditional": 2,
    "insufficient_data": 3,
    "unsuitable": 4,
}


@api_bp.route("/comparisons", methods=["POST"])
def compare_targets():
    """
    Compare one reference location against up to 5 candidate target locations (FR-11).
    Ranks targets primarily by screening status (suitable -> conditional ->
    insufficient_data -> unsuitable) and secondarily by compatibility score descending.
    """
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Request body must be a valid JSON object."}), 400

    adaptation_id = payload.get("adaptation_id")
    if not adaptation_id or not isinstance(adaptation_id, str):
        return jsonify({"error": "Missing or invalid 'adaptation_id'."}), 400

    ref_loc = payload.get("reference_location")
    if not isinstance(ref_loc, dict):
        return jsonify({"error": "'reference_location' must be an object."}), 400

    targets = payload.get("targets")
    if not isinstance(targets, list):
        return jsonify({"error": "'targets' must be a list of 1 to 5 target locations."}), 400
    if len(targets) == 0:
        return jsonify({"error": "'targets' must contain at least 1 target location."}), 400
    if len(targets) > 5:
        return jsonify({"error": "'targets' list cannot exceed 5 target locations."}), 400

    conn = _get_db_connection()
    try:
        ranked_items: List[Dict[str, Any]] = []
        for idx, tgt in enumerate(targets, start=1):
            if not isinstance(tgt, dict):
                conn.close()
                return jsonify({"error": f"Target #{idx} must be a valid object."}), 400

            tgt_name = tgt.get("name") or f"Target {idx}"
            tgt_copy = dict(tgt)
            tgt_copy["name"] = tgt_name

            res, err, status_code = _run_single_assessment(conn, adaptation_id, ref_loc, tgt_copy)
            if err:
                conn.close()
                return jsonify({"error": f"Target #{idx} ('{tgt_name}'): {err}"}), status_code

            ranked_items.append(
                {
                    "assessment_id": res["assessment_id"],
                    "target_location": res["target_location"],
                    "status": res["status"],
                    "score": res["score"],
                    "limiting_factors": res["limiting_factors"],
                    "supporting_factors": res["supporting_factors"],
                    "suggested_checks": res["suggested_checks"],
                    "data_quality_warnings": res["data_quality_warnings"],
                    "data_badge_label": res["data_badge_label"],
                    "factors": res["factors"],
                }
            )

        # Rank targets by status priority, then score descending (None scores at the end of tier)
        ranked_items.sort(
            key=lambda x: (
                _STATUS_RANK_ORDER.get(x["status"], 99),
                -float(x["score"]) if x["score"] is not None else 1e9,
            )
        )

        for rank_num, item in enumerate(ranked_items, start=1):
            item["rank"] = rank_num

        conn.commit()

        # Query adaptation display name
        cur = conn.cursor()
        cur.execute("SELECT name FROM adaptations WHERE id = ?", (adaptation_id,))
        row = cur.fetchone()
        adapt_name = row["name"] if row else adaptation_id

        ref_name = ref_loc.get("name") or "Location A"
        try:
            r_lat, r_lon = validate_coordinates(ref_loc.get("latitude"), ref_loc.get("longitude"))
        except Exception:
            r_lat, r_lon = None, None

        resp = jsonify(
            {
                "adaptation_id": adaptation_id,
                "adaptation_name": adapt_name,
                "reference_location": {
                    "name": ref_name,
                    "latitude": r_lat,
                    "longitude": r_lon,
                },
                "total_targets": len(ranked_items),
                "targets": ranked_items,
                "disclaimer": DISCLAIMER,
            }
        )
        return resp, 200
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# GET /api/assessments                                                       #
# --------------------------------------------------------------------------- #

@api_bp.route("/assessments", methods=["GET"])
def list_assessments():
    """List historical assessments, newest first, with pagination."""
    try:
        page = max(1, int(request.args.get("page", 1)))
    except (ValueError, TypeError):
        page = 1

    try:
        per_page = max(1, min(100, int(request.args.get("per_page", request.args.get("limit", 10)))))
    except (ValueError, TypeError):
        per_page = 10

    offset = (page - 1) * per_page

    conn = _get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM assessments")
    total = cur.fetchone()[0]

    cur.execute(
        """
        SELECT a.id, a.adaptation_id, ad.name AS adaptation_name, a.status, a.score, a.created_at,
               loc_a.id AS a_id, loc_a.name AS a_name, loc_a.latitude AS a_lat, loc_a.longitude AS a_lon,
               loc_b.id AS b_id, loc_b.name AS b_name, loc_b.latitude AS b_lat, loc_b.longitude AS b_lon
        FROM assessments a
        JOIN adaptations ad ON a.adaptation_id = ad.id
        JOIN locations loc_a ON a.location_a_id = loc_a.id
        JOIN locations loc_b ON a.location_b_id = loc_b.id
        ORDER BY a.created_at DESC, a.id DESC
        LIMIT ? OFFSET ?
        """,
        (per_page, offset),
    )
    rows = cur.fetchall()
    conn.close()

    items = [
        {
            "id": r["id"],
            "assessment_id": r["id"],
            "adaptation_id": r["adaptation_id"],
            "adaptation_name": r["adaptation_name"],
            "status": r["status"],
            "score": round(r["score"], 2) if r["score"] is not None else None,
            "reference_location": {
                "id": r["a_id"],
                "name": r["a_name"],
                "latitude": float(r["a_lat"]) if r["a_lat"] is not None else None,
                "longitude": float(r["a_lon"]) if r["a_lon"] is not None else None,
            },
            "target_location": {
                "id": r["b_id"],
                "name": r["b_name"],
                "latitude": float(r["b_lat"]) if r["b_lat"] is not None else None,
                "longitude": float(r["b_lon"]) if r["b_lon"] is not None else None,
            },
            "location_a": r["a_name"],
            "location_b": r["b_name"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]

    total_pages = max(1, (total + per_page - 1) // per_page) if total > 0 else 1

    return jsonify({
        "assessments": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": total_pages,
    }), 200


# --------------------------------------------------------------------------- #
# GET /api/assessments/<id>                                                  #
# --------------------------------------------------------------------------- #

def _fetch_assessment_data(
    assessment_id: int,
) -> Tuple[Optional[Dict[str, Any]], Optional[str], int]:
    """Retrieve an assessment record and format into response dictionary."""
    conn = _get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT a.id, a.adaptation_id, ad.name AS adaptation_name, a.status, a.score, a.created_at,
               la.name AS a_name, la.latitude AS a_lat, la.longitude AS a_lon,
               lb.name AS b_name, lb.latitude AS b_lat, lb.longitude AS b_lon
        FROM assessments a
        JOIN adaptations ad ON a.adaptation_id = ad.id
        JOIN locations la ON a.location_a_id = la.id
        JOIN locations lb ON a.location_b_id = lb.id
        WHERE a.id = ?
        """,
        (assessment_id,),
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return None, f"Assessment with id {assessment_id} not found.", 404

    cur.execute(
        """
        SELECT factor, a_value, b_value, factor_status, interpretation
        FROM assessment_factors
        WHERE assessment_id = ?
        ORDER BY id ASC
        """,
        (assessment_id,),
    )
    factor_rows = cur.fetchall()

    # Also load requirement summaries from adaptation_requirements
    cur.execute(
        """
        SELECT factor, min_value, max_value, unit, is_critical, transfer_tolerance,
               tolerance_type, evidence, rule_version
        FROM adaptation_requirements
        WHERE adaptation_id = ?
        """,
        (row["adaptation_id"],),
    )
    req_rows = {r["factor"]: r for r in cur.fetchall()}
    conn.close()

    factors_payload: List[Dict[str, Any]] = []
    supporting: List[str] = []
    limiting: List[str] = []

    a_lat = float(row["a_lat"]) if row["a_lat"] is not None else None
    a_lon = float(row["a_lon"]) if row["a_lon"] is not None else None
    b_lat = float(row["b_lat"]) if row["b_lat"] is not None else None
    b_lon = float(row["b_lon"]) if row["b_lon"] is not None else None

    a_env = fetch_location_environmental_data(a_lat, a_lon, name=row["a_name"]) if a_lat is not None and a_lon is not None else {"metadata": {}}
    b_env = fetch_location_environmental_data(b_lat, b_lon, name=row["b_name"]) if b_lat is not None and b_lon is not None else {"metadata": {}}

    from backend.compatibility_engine import _requirement_summary, _is_transfer_risk

    for fr in factor_rows:
        req_meta = req_rows.get(fr["factor"])
        req_summary = ""
        is_risk = False
        if req_meta:
            req_obj = Requirement(
                factor=req_meta["factor"],
                min_value=req_meta["min_value"],
                max_value=req_meta["max_value"],
                unit=req_meta["unit"] or "",
            )
            req_summary = _requirement_summary(req_obj)
            is_risk = _is_transfer_risk(
                fr["a_value"],
                fr["b_value"],
                req_meta["transfer_tolerance"],
                req_meta["tolerance_type"],
            )

        status = fr["factor_status"]
        if status == "transfer_risk":
            status = "met"
            is_risk = True

        if status == "met" and not is_risk:
            supporting.append(fr["factor"])
        if status in ("unmet", "unknown") or is_risk:
            limiting.append(fr["factor"])

        b_meta = b_env.get("metadata", {}).get(fr["factor"], {})
        a_meta = a_env.get("metadata", {}).get(fr["factor"], {})

        factors_payload.append(
            {
                "factor": fr["factor"],
                "a_value": fr["a_value"],
                "b_value": fr["b_value"],
                "requirement": req_summary,
                "factor_status": status,
                "transfer_risk": is_risk,
                "interpretation": fr["interpretation"],
                "source": b_meta.get("source") or "Demo value",
                "resolution": b_meta.get("resolution") or "n/a (demo)",
                "a_source": a_meta.get("source") or "Demo value",
                "a_resolution": a_meta.get("resolution") or "n/a (demo)",
                "b_source": b_meta.get("source") or "Demo value",
                "b_resolution": b_meta.get("resolution") or "n/a (demo)",
                "evidence": req_meta["evidence"] if req_meta and req_meta["evidence"] else "",
                "rule_version": req_meta["rule_version"] if req_meta and req_meta["rule_version"] else "",
            }
        )

    get_warnings = (
        a_env.get("warnings", [])
        + b_env.get("warnings", [])
        + generate_metadata_warnings(a_env.get("metadata", {}), location_label=row["a_name"])
        + generate_metadata_warnings(b_env.get("metadata", {}), location_label=row["b_name"])
    )
    get_rain_warn = generate_rainfall_grid_warning(
        a_env.get("metadata", {}).get("annual_rainfall", {}).get("source"),
        b_env.get("metadata", {}).get("annual_rainfall", {}).get("source"),
    )
    if get_rain_warn:
        get_warnings.append(get_rain_warn)
    deduped_warnings = list(dict.fromkeys(get_warnings))

    response_body = {
        "assessment_id": row["id"],
        "adaptation_id": row["adaptation_id"],
        "adaptation_name": row["adaptation_name"],
        "reference_location": {
            "name": row["a_name"],
            "latitude": float(row["a_lat"]) if row["a_lat"] is not None else None,
            "longitude": float(row["a_lon"]) if row["a_lon"] is not None else None,
        },
        "target_location": {
            "name": row["b_name"],
            "latitude": float(row["b_lat"]) if row["b_lat"] is not None else None,
            "longitude": float(row["b_lon"]) if row["b_lon"] is not None else None,
        },
        "location_a": {
            "name": row["a_name"],
            "latitude": float(row["a_lat"]) if row["a_lat"] is not None else None,
            "longitude": float(row["a_lon"]) if row["a_lon"] is not None else None,
        },
        "location_b": {
            "name": row["b_name"],
            "latitude": float(row["b_lat"]) if row["b_lat"] is not None else None,
            "longitude": float(row["b_lon"]) if row["b_lon"] is not None else None,
        },
        "status": row["status"],
        "score": round(row["score"], 2) if row["score"] is not None else None,
        "suitable_min": float(current_app.config.get("SUITABLE_MIN", Config.SUITABLE_MIN)),
        "max_missing_weight": float(current_app.config.get("MAX_MISSING_WEIGHT", Config.MAX_MISSING_WEIGHT)),
        "factors": factors_payload,
        "supporting_factors": supporting,
        "limiting_factors": limiting,
        "suggested_checks": [],
        "data_quality_warnings": deduped_warnings,
        "disclaimer": DISCLAIMER,
        "data_badge_label": build_data_badge_label(factors_payload),
        "created_at": row["created_at"],
        "live_rainfall_used": bool(
            a_env.get("live_rainfall_used")
            or b_env.get("live_rainfall_used")
            or any((f.get("factor") == "annual_rainfall" and ((f.get("source") or "").startswith("Live") or (f.get("b_source") or "").startswith("Live") or (f.get("a_source") or "").startswith("Live"))) for f in factors_payload)
        ),
        "live_slope_used": bool(
            a_env.get("live_slope_used")
            or b_env.get("live_slope_used")
            or any((f.get("factor") == "slope" and ((f.get("source") or "").startswith("Live") or (f.get("b_source") or "").startswith("Live") or (f.get("a_source") or "").startswith("Live"))) for f in factors_payload)
        ),
        "live_soil_used": bool(
            a_env.get("live_soil_used")
            or b_env.get("live_soil_used")
            or any((f.get("factor") == "soil_infiltration" and ((f.get("source") or "").startswith("Live") or (f.get("b_source") or "").startswith("Live") or (f.get("a_source") or "").startswith("Live"))) for f in factors_payload)
        ),
        "live_osm_used": bool(
            a_env.get("live_osm_used")
            or b_env.get("live_osm_used")
            or any((f.get("factor") in ("open_space", "building_distance") and ((f.get("source") or "").startswith("Live") or (f.get("b_source") or "").startswith("Live") or (f.get("a_source") or "").startswith("Live"))) for f in factors_payload)
        ),
    }
    return response_body, None, 200


@api_bp.route("/assessments/<int:assessment_id>", methods=["GET"])
def get_assessment(assessment_id: int):
    """Retrieve a previously saved assessment by ID."""
    data, err, status_code = _fetch_assessment_data(assessment_id)
    if err:
        return jsonify({"error": err}), status_code
    return jsonify(data), 200


@api_bp.route("/assessments/<int:assessment_id>/pdf", methods=["GET"])
def export_assessment_pdf(assessment_id: int):
    """Export an assessment to a downloadable PDF report (FR-12)."""
    data, err, status_code = _fetch_assessment_data(assessment_id)
    if err:
        return jsonify({"error": err}), status_code

    from backend.pdf_exporter import generate_assessment_pdf

    try:
        pdf_bytes = generate_assessment_pdf(data)
        filename = f"ADAPTFIT_Assessment_{assessment_id}.pdf"
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename,
        )
    except Exception as exc:
        current_app.logger.error("Failed to generate PDF for assessment %d: %s", assessment_id, exc)
        return jsonify({"error": f"Failed to generate PDF: {exc}"}), 500
