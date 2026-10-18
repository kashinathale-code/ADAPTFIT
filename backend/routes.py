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

import os
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from flask import Blueprint, current_app, jsonify, request

from backend.compatibility_engine import (
    EngineConfig,
    Requirement,
    assess,
)
from backend.data_fetcher import (
    FACTOR_KEYS,
    FACTOR_UNITS,
    fetch_location_environmental_data,
)
from backend.data_processor import (
    clean_environmental_value,
    generate_metadata_warnings,
    validate_coordinates,
)
from config import Config

api_bp = Blueprint("api", __name__, url_prefix="/api")


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
    """List available adaptation interventions from the knowledge base."""
    conn = _get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name, description, evidence_source FROM adaptations")
    rows = cur.fetchall()
    conn.close()

    adaptations = [
        {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "evidence_source": row["evidence_source"],
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
    }
    return jsonify(response_payload), 200


# --------------------------------------------------------------------------- #
# POST /api/assessments                                                       #
# --------------------------------------------------------------------------- #

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

    # Validate coordinates
    try:
        ref_lat, ref_lon = validate_coordinates(
            ref_loc.get("latitude"), ref_loc.get("longitude")
        )
    except ValueError as err:
        return (
            jsonify({"error": f"Invalid reference_location coordinates: {err}"}),
            400,
        )

    try:
        tgt_lat, tgt_lon = validate_coordinates(
            tgt_loc.get("latitude"), tgt_loc.get("longitude")
        )
    except ValueError as err:
        return (
            jsonify({"error": f"Invalid target_location coordinates: {err}"}),
            400,
        )

    conn = _get_db_connection()
    cur = conn.cursor()

    # Validate adaptation exists (404 if not found)
    cur.execute("SELECT id, name FROM adaptations WHERE id = ?", (adaptation_id,))
    adapt_row = cur.fetchone()
    if not adapt_row:
        conn.close()
        return (
            jsonify({"error": f"Unknown adaptation '{adaptation_id}'."}),
            404,
        )

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
        conn.close()
        return (
            jsonify({"error": f"No requirements defined for adaptation '{adaptation_id}'."}),
            400,
        )

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
    src_res_warnings = (
        fetched_a["warnings"]
        + fetched_b["warnings"]
        + generate_metadata_warnings(meta_a, location_label=ref_name)
        + generate_metadata_warnings(meta_b, location_label=tgt_name)
    )
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
        # Determine factor status representation matching TRD §5 schema
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
                "transfer_risk" if fr.transfer_risk else fr.factor_status,
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
            }
        )

    conn.commit()
    conn.close()

    # Response strictly matching TRD Section 7
    response_body = {
        "assessment_id": assessment_id,
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
        "factors": factors_payload,
        "supporting_factors": assessment_res.supporting_factors,
        "limiting_factors": assessment_res.limiting_factors,
        "suggested_checks": assessment_res.suggested_checks,
        "data_quality_warnings": combined_warnings,
        "disclaimer": assessment_res.disclaimer,
    }
    return jsonify(response_body), 201


# --------------------------------------------------------------------------- #
# GET /api/assessments/<id>                                                  #
# --------------------------------------------------------------------------- #

@api_bp.route("/assessments/<int:assessment_id>", methods=["GET"])
def get_assessment(assessment_id: int):
    """Retrieve a previously saved assessment by ID."""
    conn = _get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT a.id, a.adaptation_id, a.status, a.score, a.created_at,
               la.name AS a_name, la.latitude AS a_lat, la.longitude AS a_lon,
               lb.name AS b_name, lb.latitude AS b_lat, lb.longitude AS b_lon
        FROM assessments a
        JOIN locations la ON a.location_a_id = la.id
        JOIN locations lb ON a.location_b_id = lb.id
        WHERE a.id = ?
        """,
        (assessment_id,),
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return jsonify({"error": f"Assessment with id {assessment_id} not found."}), 404

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
        SELECT factor, min_value, max_value, unit, is_critical, transfer_tolerance, tolerance_type
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

    for fr in factor_rows:
        req_meta = req_rows.get(fr["factor"])
        req_summary = ""
        if req_meta:
            req_obj = Requirement(
                factor=req_meta["factor"],
                min_value=req_meta["min_value"],
                max_value=req_meta["max_value"],
                unit=req_meta["unit"] or "",
            )
            from backend.compatibility_engine import _requirement_summary
            req_summary = _requirement_summary(req_obj)

        is_risk = fr["factor_status"] == "transfer_risk"
        status = "met" if is_risk else fr["factor_status"]

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
            }
        )

    from backend.compatibility_engine import DISCLAIMER
    response_body = {
        "assessment_id": row["id"],
        "adaptation_id": row["adaptation_id"],
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
        "factors": factors_payload,
        "supporting_factors": supporting,
        "limiting_factors": limiting,
        "suggested_checks": [],
        "data_quality_warnings": [],
        "disclaimer": DISCLAIMER,
        "created_at": row["created_at"],
    }
    return jsonify(response_body), 200
