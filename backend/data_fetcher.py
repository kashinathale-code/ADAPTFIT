"""
ADAPTFIT Data Fetcher
=====================
Reads environmental data from datasets/sample_environmental_data.csv
and returns values with source, resolution, and units, with missing
values represented strictly as None (null in JSON).
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import math
import os
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

import requests

from config import Config

# Standard factor units used across ADAPTFIT
FACTOR_UNITS: Dict[str, str] = {
    "annual_rainfall": "mm/yr",
    "slope": "%",
    "soil_infiltration": "mm/hr",
    "open_space": "binary (1=present, 0=absent)",
    "building_distance": "m",
}

FACTOR_KEYS: List[str] = [
    "annual_rainfall",
    "slope",
    "soil_infiltration",
    "open_space",
    "building_distance",
]

DEFAULT_CSV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "datasets",
    "sample_environmental_data.csv",
)

# NASA POWER Climatology configuration
NASA_POWER_POINT_URL = "https://power.larc.nasa.gov/api/temporal/climatology/point"
NASA_POWER_RESOLUTION = "0.5° × 0.5° (~50 km × 50 km coarse grid)"
NASA_POWER_SOURCE = "Live: NASA POWER"
DEMO_SOURCE = "Demo value"
DEMO_RESOLUTION = "n/a (demo)"


def get_cached_rainfall(
    lat: float,
    lon: float,
    db_path: str,
    staleness_hours: int = 24,
) -> Optional[Dict[str, Any]]:
    """Retrieve non-stale cached annual_rainfall feature from SQLite if present."""
    if not os.path.exists(db_path):
        return None
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            SELECT ef.value, ef.unit, ef.source, ef.resolution, ef.data_date, ef.retrieved_at, ef.transformation
            FROM environmental_features ef
            JOIN locations l ON ef.location_id = l.id
            WHERE ef.factor = 'annual_rainfall'
              AND abs(l.latitude - ?) < 0.0001
              AND abs(l.longitude - ?) < 0.0001
            ORDER BY ef.id DESC
            LIMIT 1
            """,
            (lat, lon),
        )
        row = cur.fetchone()
        conn.close()
        if not row or not row["retrieved_at"]:
            return None

        # Check staleness
        try:
            retrieved_dt = datetime.fromisoformat(row["retrieved_at"])
            if retrieved_dt.tzinfo is None:
                retrieved_dt = retrieved_dt.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            age_hours = (now - retrieved_dt).total_seconds() / 3600.0
            if age_hours < staleness_hours:
                return {
                    "value": row["value"],
                    "unit": row["unit"] or "mm/yr",
                    "source": row["source"] or NASA_POWER_SOURCE,
                    "resolution": row["resolution"] or NASA_POWER_RESOLUTION,
                    "data_date": row["data_date"],
                    "retrieved_at": row["retrieved_at"],
                    "transformation": row["transformation"],
                }
        except (ValueError, TypeError):
            return None
    except sqlite3.Error:
        return None
    return None


def cache_rainfall(
    lat: float,
    lon: float,
    value: float,
    unit: str,
    source: str,
    resolution: str,
    data_date: str,
    retrieved_at: str,
    transformation: str,
    db_path: str,
    name: Optional[str] = None,
) -> None:
    """Store retrieved rainfall in locations and environmental_features tables."""
    if not os.path.exists(db_path):
        return
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        cur = conn.cursor()

        # Check if location already exists
        cur.execute(
            "SELECT id FROM locations WHERE abs(latitude - ?) < 0.0001 AND abs(longitude - ?) < 0.0001 LIMIT 1",
            (lat, lon),
        )
        loc_row = cur.fetchone()
        if loc_row:
            loc_id = loc_row[0]
        else:
            loc_name = name or f"Point ({lat:.4f}, {lon:.4f})"
            cur.execute(
                "INSERT INTO locations (name, latitude, longitude) VALUES (?, ?, ?)",
                (loc_name, lat, lon),
            )
            loc_id = cur.lastrowid

        # Check if feature already exists for this location
        cur.execute(
            "SELECT id FROM environmental_features WHERE location_id = ? AND factor = 'annual_rainfall' LIMIT 1",
            (loc_id,),
        )
        ef_row = cur.fetchone()
        if ef_row:
            cur.execute(
                """
                UPDATE environmental_features
                SET value = ?, unit = ?, source = ?, resolution = ?, data_date = ?, retrieved_at = ?, transformation = ?
                WHERE id = ?
                """,
                (value, unit, source, resolution, data_date, retrieved_at, transformation, ef_row[0]),
            )
        else:
            cur.execute(
                """
                INSERT INTO environmental_features
                    (location_id, factor, value, unit, source, resolution, data_date, retrieved_at, transformation)
                VALUES (?, 'annual_rainfall', ?, ?, ?, ?, ?, ?, ?)
                """,
                (loc_id, value, unit, source, resolution, data_date, retrieved_at, transformation),
            )
        conn.commit()
        conn.close()
    except sqlite3.Error:
        pass


def fetch_nasa_power_rainfall(
    lat: float,
    lon: float,
    db_path: Optional[str] = None,
    staleness_hours: int = 24,
    timeout: float = 10.0,
    name: Optional[str] = None,
) -> Tuple[Optional[float], Optional[Dict[str, Any]], Optional[str]]:
    """
    Fetch annual rainfall from NASA POWER climatology point API with SQLite caching.

    Returns:
        (value_mm_yr, metadata_dict, error_warning)
    """
    target_db = db_path or Config.DATABASE_PATH

    # 1. Check cache first
    cached = get_cached_rainfall(lat, lon, target_db, staleness_hours=staleness_hours)
    if cached is not None:
        return (
            cached["value"],
            {
                "unit": cached["unit"],
                "source": cached["source"],
                "resolution": cached["resolution"],
                "data_date": cached["data_date"],
                "retrieved_at": cached["retrieved_at"],
                "transformation": cached["transformation"],
            },
            None,
        )

    # 2. Call NASA POWER API (PRECTOTCORR climatology annual mean)
    params = {
        "parameters": "PRECTOTCORR",
        "community": "AG",
        "latitude": lat,
        "longitude": lon,
        "format": "JSON",
    }
    try:
        resp = requests.get(NASA_POWER_POINT_URL, params=params, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        param_dict = data.get("properties", {}).get("parameter", {}).get("PRECTOTCORR", {})
        ann_daily = param_dict.get("ANN")

        if ann_daily is None or ann_daily < 0:
            return None, None, "Live rainfall data from NASA POWER was unavailable; fell back to demo/sample data."

        # Convert daily mm/day to annual mm/year
        ann_yearly = round(ann_daily * 365.25, 1)
        now_iso = datetime.now(timezone.utc).isoformat()
        transformation = "Converted from mm/day to mm/year (PRECTOTCORR ANN * 365.25)"
        data_date = "Climatology (multi-year mean)"

        meta = {
            "unit": "mm/yr",
            "source": NASA_POWER_SOURCE,
            "resolution": NASA_POWER_RESOLUTION,
            "data_date": data_date,
            "retrieved_at": now_iso,
            "transformation": transformation,
        }

        # Cache in database
        cache_rainfall(
            lat=lat,
            lon=lon,
            value=ann_yearly,
            unit="mm/yr",
            source=NASA_POWER_SOURCE,
            resolution=NASA_POWER_RESOLUTION,
            data_date=data_date,
            retrieved_at=now_iso,
            transformation=transformation,
            db_path=target_db,
            name=name,
        )

        return ann_yearly, meta, None

    except (requests.RequestException, ValueError, KeyError):
        return None, None, "Live rainfall data from NASA POWER was unavailable; fell back to demo/sample data."


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great-circle distance between two points in kilometers."""
    r = 6371.0  # Earth radius in kilometers
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c


def _parse_float(val: Any) -> Optional[float]:
    """Parse string or number to float, returning None if empty or invalid."""
    if val is None:
        return None
    val_str = str(val).strip()
    if not val_str:
        return None
    try:
        return float(val_str)
    except (ValueError, TypeError):
        return None


def _parse_str(val: Any) -> Optional[str]:
    """Return trimmed string or None if empty."""
    if val is None:
        return None
    val_str = str(val).strip()
    return val_str if val_str else None


def load_sample_locations(csv_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Load all rows from sample_environmental_data.csv.
    Missing environmental values are returned as None.
    """
    path = csv_path or DEFAULT_CSV_PATH
    if not os.path.exists(path):
        return []

    locations: List[Dict[str, Any]] = []
    with open(path, mode="r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            name = _parse_str(row.get("name"))
            lat = _parse_float(row.get("latitude"))
            lon = _parse_float(row.get("longitude"))
            if lat is None or lon is None:
                continue

            factors: Dict[str, Optional[float]] = {}
            for k in FACTOR_KEYS:
                factors[k] = _parse_float(row.get(k))

            source = _parse_str(row.get("source"))
            resolution = _parse_str(row.get("resolution"))
            data_date = _parse_str(row.get("data_date"))

            locations.append(
                {
                    "name": name,
                    "latitude": lat,
                    "longitude": lon,
                    "factors": factors,
                    "source": source,
                    "resolution": resolution,
                    "data_date": data_date,
                }
            )
    return locations


def fetch_location_environmental_data(
    lat: float,
    lon: float,
    name: Optional[str] = None,
    csv_path: Optional[str] = None,
    max_distance_km: float = 50.0,
    use_live_rainfall: Optional[bool] = None,
    db_path: Optional[str] = None,
    staleness_hours: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Fetch environmental values and metadata for a given coordinate or location name.
    
    If use_live_rainfall is True, annual_rainfall is fetched from NASA POWER with SQLite
    caching (falling back to CSV on failure/timeout). All other factors (slope,
    soil_infiltration, open_space, building_distance) stay from the CSV.
    When use_live_rainfall is False, behaviour is exactly as default (CSV only).
    """
    if use_live_rainfall is None:
        try:
            from flask import current_app
            if current_app:
                use_live_rainfall = current_app.config.get("USE_LIVE_RAINFALL", False)
            else:
                use_live_rainfall = getattr(Config, "USE_LIVE_RAINFALL", False)
        except (RuntimeError, ImportError):
            use_live_rainfall = getattr(Config, "USE_LIVE_RAINFALL", False)

    if staleness_hours is None:
        try:
            from flask import current_app
            if current_app:
                staleness_hours = current_app.config.get("CACHE_STALENESS_HOURS", Config.CACHE_STALENESS_HOURS)
            else:
                staleness_hours = getattr(Config, "CACHE_STALENESS_HOURS", 24)
        except (RuntimeError, ImportError):
            staleness_hours = getattr(Config, "CACHE_STALENESS_HOURS", 24)

    if db_path is None:
        try:
            from flask import current_app
            if current_app:
                db_path = current_app.config.get("DATABASE_PATH", Config.DATABASE_PATH)
            else:
                db_path = getattr(Config, "DATABASE_PATH", "database/adaptfit.db")
        except (RuntimeError, ImportError):
            db_path = getattr(Config, "DATABASE_PATH", "database/adaptfit.db")

    sample_records = load_sample_locations(csv_path=csv_path)

    matched_record: Optional[Dict[str, Any]] = None
    min_dist: Optional[float] = None

    # First attempt exact name match if provided
    if name:
        clean_name = name.strip().lower()
        for rec in sample_records:
            if rec.get("name") and rec["name"].strip().lower() == clean_name:
                matched_record = rec
                min_dist = haversine_distance(lat, lon, rec["latitude"], rec["longitude"])
                break

    # Otherwise find nearest coordinate
    if not matched_record and sample_records:
        best_rec = None
        best_dist = float("inf")
        for rec in sample_records:
            d = haversine_distance(lat, lon, rec["latitude"], rec["longitude"])
            if d < best_dist:
                best_dist = d
                best_rec = rec
        if best_rec and best_dist <= max_distance_km:
            matched_record = best_rec
            min_dist = round(best_dist, 2)

    values: Dict[str, Optional[float]] = {}
    metadata: Dict[str, Dict[str, Any]] = {}
    warnings: List[str] = []

    if matched_record:
        matched_name = matched_record.get("name")
        rec_res = matched_record.get("resolution") or DEMO_RESOLUTION
        rec_date = matched_record.get("data_date")

        for k in FACTOR_KEYS:
            val = matched_record["factors"].get(k)
            values[k] = val
            metadata[k] = {
                "unit": FACTOR_UNITS.get(k, ""),
                "source": DEMO_SOURCE,
                "resolution": rec_res,
                "data_date": rec_date,
            }

        if min_dist is not None and min_dist > 5.0:
            warnings.append(
                f"Using closest sample location '{matched_name}' "
                f"({min_dist:.1f} km away); site survey recommended."
            )
    else:
        # Location is outside dataset coverage
        for k in FACTOR_KEYS:
            values[k] = None
            metadata[k] = {
                "unit": FACTOR_UNITS.get(k, ""),
                "source": None,
                "resolution": None,
                "data_date": None,
            }
        warnings.append(
            f"Location ({lat:.4f}, {lon:.4f}) is outside sample dataset coverage "
            f"(~{int(max_distance_km)} km radius); all environmental values are unknown."
        )

    # If live rainfall flag is enabled: fetch NASA POWER for annual_rainfall
    live_rainfall_used = False
    if use_live_rainfall:
        live_val, live_meta, live_warn = fetch_nasa_power_rainfall(
            lat=lat,
            lon=lon,
            db_path=db_path,
            staleness_hours=staleness_hours,
            timeout=10.0,
            name=name or (matched_record.get("name") if matched_record else None),
        )
        if live_val is not None and live_meta is not None:
            values["annual_rainfall"] = live_val
            metadata["annual_rainfall"] = live_meta
            live_rainfall_used = True
        else:
            # Fallback to CSV value (already in values["annual_rainfall"])
            if live_warn:
                warnings.append(live_warn)
            if matched_record and values.get("annual_rainfall") is not None:
                metadata["annual_rainfall"]["source"] = DEMO_SOURCE

    return {
        "name": name or (matched_record.get("name") if matched_record else None),
        "latitude": lat,
        "longitude": lon,
        "matched_sample_location": matched_record.get("name") if matched_record else None,
        "distance_km": min_dist,
        "values": values,
        "metadata": metadata,
        "warnings": warnings,
        "live_rainfall_used": live_rainfall_used,
    }
