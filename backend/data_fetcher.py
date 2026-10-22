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
import json
import math
import os
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

from config import Config
from backend.gis_processor import (
    haversine_distance,
    get_slope_sampling_offsets,
    calculate_slope_from_elevations,
)

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

# Open-Meteo Elevation API configuration (Copernicus DEM GLO-90)
OPEN_METEO_ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"
OPEN_METEO_ELEVATION_SOURCE = "Live: Open-Meteo (Copernicus DEM)"
OPEN_METEO_ELEVATION_RESOLUTION = "90m (Copernicus DEM GLO-90)"
OPEN_METEO_DATA_DATE = "Copernicus DEM 2021 release"

# SoilGrids REST API configuration
# Provides USDA soil texture class (TEXCLSS) at 0-30 cm depth.
SOILGRIDS_PROPERTIES_URL = "https://rest.isric.org/soilgrids/v2.0/properties/query"
SOILGRIDS_SOURCE = "Estimated (proxy): SoilGrids v2.0 (ISRIC)"
SOILGRIDS_RESOLUTION = "250m (SoilGrids v2.0)"
SOILGRIDS_DATA_DATE = "SoilGrids v2.0 (compiled 2020)"

# ---------------------------------------------------------------------------
# Rawls et al. (1983) saturated hydraulic conductivity (Ks) lookup table
# ---------------------------------------------------------------------------
# Source:
#   Rawls, W.J., Brakensiek, D.L. & Miller, N. (1983). "Green-Ampt
#   infiltration parameters from soil data." Journal of Hydraulic
#   Engineering, 109(1), 62-70. https://doi.org/10.1061/(ASCE)0733-9429(1983)109:1(62)
#
# Ks values in mm/hr represent the long-run steady-state saturated
# infiltration rate and are used as a proxy for soil_infiltration.
# Texture class names are normalised to USDA convention for matching
# SoilGrids TEXCLSS values.
#
# | USDA Texture Class  | Ks (mm/hr) |
# |---------------------|------------|
# | Sand                |   117.8    |
# | Loamy sand          |    29.9    |
# | Sandy loam          |    10.9    |
# | Loam                |     3.4    |
# | Silt loam           |     6.5    |
# | Sandy clay loam     |     1.5    |
# | Clay loam           |     1.0    |
# | Silty clay loam     |     1.0    |
# | Sandy clay          |     0.6    |
# | Silty clay          |     0.5    |
# | Clay                |     0.3    |

RAWLS_1983_KS_TABLE: Dict[str, float] = {
    "sand": 117.8,
    "loamy sand": 29.9,
    "sandy loam": 10.9,
    "loam": 3.4,
    "silt loam": 6.5,
    "sandy clay loam": 1.5,
    "clay loam": 1.0,
    "silty clay loam": 1.0,
    "sandy clay": 0.6,
    "silty clay": 0.5,
    "clay": 0.3,
    # Aliases used in SoilGrids TEXCLSS labels
    "silt": 6.5,           # treat as silt loam (conservative)
    "sandy clay loam": 1.5,
    "loamy fine sand": 10.9,  # treat as sandy loam
    "fine sand": 29.9,     # treat as loamy sand
    "coarse sand": 117.8,  # treat as sand
}


def infiltration_from_texture(texture_class: str) -> Optional[float]:
    """
    Look up saturated hydraulic conductivity (mm/hr) from a USDA texture
    class name using the Rawls et al. (1983) table.

    The lookup is case-insensitive and strips surrounding whitespace.
    Returns None if the texture class is not in the table.
    """
    key = texture_class.strip().lower()
    if key in RAWLS_1983_KS_TABLE:
        return RAWLS_1983_KS_TABLE[key]
    # Try prefix matching for variants like "Loamy Fine Sand"
    for table_key, ks in RAWLS_1983_KS_TABLE.items():
        if key.startswith(table_key) or table_key.startswith(key):
            return ks
    return None


def classify_usda_texture(sand: float, silt: float, clay: float) -> Optional[str]:
    """
    Classify soil texture into one of the 12 USDA texture classes based on
    sand, silt, and clay percentages according to the USDA Soil Survey Manual
    (Handbook No. 18, Chapter 3).

    Returns lowercase class name (e.g. 'loam', 'clay loam') matching RAWLS_1983_KS_TABLE,
    or None if input values are invalid.
    """
    if sand is None or silt is None or clay is None:
        return None
    try:
        tot = float(sand) + float(silt) + float(clay)
    except (ValueError, TypeError):
        return None
    if tot <= 0:
        return None
    s = (float(sand) / tot) * 100.0
    si = (float(silt) / tot) * 100.0
    c = (float(clay) / tot) * 100.0

    if c >= 40:
        if si >= 40:
            return "silty clay"
        elif s >= 45:
            return "sandy clay"
        else:
            return "clay"
    elif c >= 35:
        if s >= 45:
            return "sandy clay"
        elif s <= 20 or si >= 40:
            return "silty clay loam"
        elif s <= 45:
            return "clay loam"
        else:
            return "sandy clay loam"
    elif c >= 27:
        if s <= 20:
            return "silty clay loam"
        elif s <= 45:
            return "clay loam"
        else:
            return "sandy clay loam"
    elif c >= 20:
        if s >= 45 and si < 28:
            return "sandy clay loam"
        elif si >= 50:
            return "silt loam"
        elif s <= 52 and si >= 28:
            return "loam"
        elif s > 52:
            return "sandy loam"
        else:
            return "loam"
    elif c >= 12:
        if si >= 50:
            return "silt loam"
        elif s > 52 and (si + 2 * c >= 30):
            return "sandy loam"
        elif s <= 52 and si >= 28:
            return "loam"
        else:
            return "sandy loam" if s > 52 else "loam"
    elif c >= 7:
        if si >= 80:
            return "silt"
        elif si >= 50:
            return "silt loam"
        elif s <= 52 and si >= 28:
            return "loam"
        elif si + 2 * c < 30:
            if si + 1.5 * c < 15:
                return "sand"
            else:
                return "loamy sand"
        else:
            return "sandy loam"
    else:  # c < 7
        if si >= 80:
            return "silt"
        elif si >= 50:
            return "silt loam"
        elif si + 2 * c < 30:
            if si + 1.5 * c < 15:
                return "sand"
            else:
                return "loamy sand"
        else:
            return "sandy loam"


# OpenStreetMap Overpass API configuration
# open_space: parks/greenery within 500 m radius (binary 1/0)
# building_distance: nearest building centroid distance in metres (within 200 m)
OSM_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OSM_SOURCE = "Live: OpenStreetMap (Overpass)"
OSM_RESOLUTION = "~1m positional (OSM contributor data)"
OSM_DATA_DATE = "OpenStreetMap (retrieved at query time)"
# Radius for open-space detection (metres)
OSM_OPEN_SPACE_RADIUS_M = 500
# Radius for building search (metres)
OSM_BUILDING_RADIUS_M = 200

# Overpass mirrors tried sequentially in order
OVERPASS_MIRRORS: List[str] = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

DEFAULT_SNAPSHOTS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "datasets",
    "live_snapshots.json",
)

DEMO_SOURCE = "Demo value"
DEMO_RESOLUTION = "n/a (demo)"


def _get_user_agent() -> str:
    """Return descriptive User-Agent configured in Config.HTTP_USER_AGENT."""
    try:
        from flask import current_app
        if current_app:
            return current_app.config.get("HTTP_USER_AGENT", getattr(Config, "HTTP_USER_AGENT", "ADAPTFIT/1.0"))
    except Exception:
        pass
    return getattr(
        Config,
        "HTTP_USER_AGENT",
        "ADAPTFIT/1.0 (Climate Adaptation Transferability Tool; https://github.com/adaptfit; contact: research@adaptfit.org)",
    )


def _request_with_retry(
    method: str,
    url: str,
    retries: int = 2,
    connect_timeout: float = 5.0,
    read_timeout: float = 10.0,
    **kwargs,
) -> requests.Response:
    """
    Execute HTTP request with descriptive User-Agent, connect timeout (5s by default),
    and retry loop (2 retries).
    """
    headers = dict(kwargs.pop("headers", None) or {})
    if "User-Agent" not in headers and "user-agent" not in headers:
        headers["User-Agent"] = _get_user_agent()

    raw_timeout = kwargs.pop("timeout", None)
    if isinstance(raw_timeout, tuple):
        timeout_val = raw_timeout
    elif isinstance(raw_timeout, (int, float)):
        timeout_val = (connect_timeout, float(raw_timeout))
    else:
        timeout_val = (connect_timeout, read_timeout)

    last_exc: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            if method.upper() == "POST":
                resp = requests.post(url, headers=headers, timeout=timeout_val, **kwargs)
            else:
                resp = requests.get(url, headers=headers, timeout=timeout_val, **kwargs)

            if resp.status_code >= 500 or resp.status_code == 429:
                resp.raise_for_status()
            return resp
        except (requests.RequestException, Exception) as exc:
            last_exc = exc
            if attempt < retries:
                if "PYTEST_CURRENT_TEST" not in os.environ:
                    time.sleep(0.1 * (2 ** attempt))
                continue
            raise last_exc

    if last_exc:
        raise last_exc
    raise RuntimeError(f"Request to {url} failed without exception")


def load_live_snapshots(snapshots_path: Optional[str] = None) -> Dict[str, Any]:
    """Load JSON file containing saved live snapshots for demo locations."""
    path = DEFAULT_SNAPSHOTS_PATH if snapshots_path is None else snapshots_path
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {}


def get_saved_snapshot(
    factor: str,
    lat: float,
    lon: float,
    name: Optional[str] = None,
    snapshots_path: Optional[str] = None,
    max_distance_km: float = 15.0,
) -> Optional[Dict[str, Any]]:
    """
    Look up a saved snapshot for the given factor and location.
    Matches by name (case-insensitive) or by proximity within max_distance_km.
    Returns factor snapshot dict if found, else None.
    """
    data = load_live_snapshots(snapshots_path)
    if not data or not isinstance(data, dict):
        return None

    locations = data.get("locations", {})
    if not isinstance(locations, dict):
        return None

    matched_loc = None

    # 1. Name match
    if name:
        clean_name = name.strip().lower()
        for loc_key, loc in locations.items():
            loc_name = loc.get("name", "").strip().lower()
            if loc_name == clean_name or loc_key.lower() == clean_name or clean_name in loc_name or loc_name in clean_name:
                matched_loc = loc
                break

    # 2. Coordinate proximity match if name match not found
    if not matched_loc:
        best_dist = float("inf")
        best_loc = None
        for loc in locations.values():
            l_lat = loc.get("latitude")
            l_lon = loc.get("longitude")
            if l_lat is not None and l_lon is not None:
                d = haversine_distance(lat, lon, float(l_lat), float(l_lon))
                if d < best_dist:
                    best_dist = d
                    best_loc = loc
        if best_loc and best_dist <= max_distance_km:
            matched_loc = best_loc

    if not matched_loc:
        return None

    factors = matched_loc.get("factors", {})
    if factor in factors:
        return factors[factor]
    return None


# In-memory telemetry tracker for external data sources
DATA_SOURCES_TELEMETRY: Dict[str, Dict[str, Optional[str]]] = {
    "nasa_power": {"last_success": None, "last_error": None},
    "open_meteo": {"last_success": None, "last_error": None},
    "soilgrids": {"last_success": None, "last_error": None},
    "overpass": {"last_success": None, "last_error": None},
}


def get_snapshot_file_date(snapshots_path: Optional[str] = None) -> str:
    """Return the snapshot fetch date recorded in datasets/live_snapshots.json."""
    snaps = load_live_snapshots(snapshots_path)
    if snaps and snaps.get("fetch_date"):
        return str(snaps["fetch_date"])
    target_path = snapshots_path or DEFAULT_SNAPSHOTS_PATH
    if os.path.exists(target_path):
        mtime = os.path.getmtime(target_path)
        return datetime.fromtimestamp(mtime, timezone.utc).strftime("%Y-%m-%d")
    return "2026-10-22"


def get_data_sources_telemetry(db_path: Optional[str] = None) -> Dict[str, Dict[str, Optional[str]]]:
    """
    Return telemetry on last successful fetch and last error per source.
    If in-memory timestamp is None, inspects SQLite environmental_features table.
    """
    telemetry = {
        "nasa_power": dict(DATA_SOURCES_TELEMETRY["nasa_power"]),
        "open_meteo": dict(DATA_SOURCES_TELEMETRY["open_meteo"]),
        "soilgrids": dict(DATA_SOURCES_TELEMETRY["soilgrids"]),
        "overpass": dict(DATA_SOURCES_TELEMETRY["overpass"]),
    }

    target_db = db_path or Config.DATABASE_PATH
    if os.path.exists(target_db):
        try:
            conn = sqlite3.connect(target_db)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            # Check NASA POWER
            if not telemetry["nasa_power"]["last_success"]:
                cur.execute(
                    "SELECT retrieved_at FROM environmental_features WHERE source LIKE 'Live: NASA POWER%' ORDER BY id DESC LIMIT 1"
                )
                row = cur.fetchone()
                if row and row["retrieved_at"]:
                    telemetry["nasa_power"]["last_success"] = row["retrieved_at"]

            # Check Open-Meteo
            if not telemetry["open_meteo"]["last_success"]:
                cur.execute(
                    "SELECT retrieved_at FROM environmental_features WHERE source LIKE 'Live: Open-Meteo%' ORDER BY id DESC LIMIT 1"
                )
                row = cur.fetchone()
                if row and row["retrieved_at"]:
                    telemetry["open_meteo"]["last_success"] = row["retrieved_at"]

            # Check SoilGrids
            if not telemetry["soilgrids"]["last_success"]:
                cur.execute(
                    "SELECT retrieved_at FROM environmental_features WHERE source LIKE '%SoilGrids%' ORDER BY id DESC LIMIT 1"
                )
                row = cur.fetchone()
                if row and row["retrieved_at"]:
                    telemetry["soilgrids"]["last_success"] = row["retrieved_at"]

            # Check Overpass (non-snapshot)
            if not telemetry["overpass"]["last_success"]:
                cur.execute(
                    "SELECT retrieved_at FROM environmental_features WHERE source LIKE 'Live: OpenStreetMap%' AND source NOT LIKE '%cached snapshot%' ORDER BY id DESC LIMIT 1"
                )
                row = cur.fetchone()
                if row and row["retrieved_at"]:
                    telemetry["overpass"]["last_success"] = row["retrieved_at"]

            conn.close()
        except Exception:
            pass

    return telemetry


def load_snapshots_into_cache(db_path: Optional[str] = None, snapshots_path: Optional[str] = None) -> int:
    """
    Load live data snapshots from datasets/live_snapshots.json into SQLite environmental_features table.
    ONLY values that were REALLY FETCHED (value is not None) are loaded, labeled
    'Live (cached snapshot, <fetch date>)'.
    Values that are null/unmeasured stay Demo values from CSV or seed.
    Returns the count of loaded features.
    """
    target_db = db_path or Config.DATABASE_PATH
    if not os.path.exists(target_db):
        return 0

    snaps = load_live_snapshots(snapshots_path)
    if not snaps:
        return 0

    global_date = snaps.get("fetch_date", "2026-10-22")
    locations = snaps.get("locations", {})
    count = 0

    try:
        conn = sqlite3.connect(target_db, timeout=30.0)
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        for loc_key, loc_info in locations.items():
            name = loc_info.get("name")
            lat = loc_info.get("latitude")
            lon = loc_info.get("longitude")
            if lat is None or lon is None:
                continue

            # Look up or insert location
            cur.execute(
                "SELECT id FROM locations WHERE ABS(latitude - ?) < 0.001 AND ABS(longitude - ?) < 0.001 LIMIT 1",
                (lat, lon),
            )
            loc_row = cur.fetchone()
            if loc_row:
                loc_id = loc_row["id"]
            else:
                cur.execute(
                    "INSERT INTO locations (name, latitude, longitude) VALUES (?, ?, ?)",
                    (name or loc_key.replace("_", " ").title(), lat, lon),
                )
                loc_id = cur.lastrowid

            factors = loc_info.get("factors", {})
            for factor_key, factor_dict in factors.items():
                val = factor_dict.get("value")
                # ONLY for values really fetched!
                if val is None:
                    continue

                fetch_date = factor_dict.get("fetch_date") or global_date
                source_label = f"Live (cached snapshot, {fetch_date})"
                unit = factor_dict.get("unit", "")
                resolution = factor_dict.get("resolution", "")
                data_date = factor_dict.get("data_date") or fetch_date
                transformation = factor_dict.get("transformation", "Retrieved from cached live snapshot")
                now_iso = datetime.now(timezone.utc).isoformat()

                # Check if feature already exists
                cur.execute(
                    "SELECT id, source FROM environmental_features WHERE location_id = ? AND factor = ? LIMIT 1",
                    (loc_id, factor_key),
                )
                existing = cur.fetchone()
                if not existing:
                    cur.execute(
                        """
                        INSERT INTO environmental_features
                            (location_id, factor, value, unit, source, resolution, data_date, retrieved_at, transformation)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (loc_id, factor_key, val, unit, source_label, resolution, data_date, now_iso, transformation),
                    )
                    count += 1
                elif existing["source"] and not existing["source"].startswith("Live:"):
                    cur.execute(
                        """
                        UPDATE environmental_features
                        SET value = ?, unit = ?, source = ?, resolution = ?, data_date = ?, retrieved_at = ?, transformation = ?
                        WHERE id = ?
                        """,
                        (val, unit, source_label, resolution, data_date, now_iso, transformation, existing["id"]),
                    )
                    count += 1

        conn.commit()
        conn.close()
    except Exception:
        pass

    return count


def warm_cache_demo_locations(db_path: Optional[str] = None, csv_path: Optional[str] = None) -> None:
    """
    Warm cache for demonstration locations (Pune, Pimpri, Niphad, Lonavala, Nashik)
    by fetching live environmental data. Run in a background thread at startup.
    Never blocks boot and never raises exceptions.
    """
    demo_locs = [
        ("Pune city", 18.5204, 73.8567),
        ("Pimpri", 18.6298, 73.7997),
        ("Niphad", 20.0800, 74.1100),
        ("Lonavala", 18.7557, 73.4091),
        ("Nashik city", 19.9975, 73.7898),
    ]
    target_db = db_path or Config.DATABASE_PATH
    for name, lat, lon in demo_locs:
        try:
            fetch_location_environmental_data(
                lat=lat,
                lon=lon,
                name=name,
                csv_path=csv_path,
                db_path=target_db,
                use_live_rainfall=True,
                use_live_slope=True,
                use_live_soil=True,
                use_live_osm=True,
            )
        except Exception:
            pass



def get_cached_feature(
    factor: str,
    lat: float,
    lon: float,
    db_path: str,
    staleness_hours: int = 24,
) -> Optional[Dict[str, Any]]:
    """Retrieve non-stale cached environmental feature from SQLite if present."""
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
            WHERE ef.factor = ?
              AND abs(l.latitude - ?) < 0.0001
              AND abs(l.longitude - ?) < 0.0001
            ORDER BY ef.id DESC
            LIMIT 1
            """,
            (factor, lat, lon),
        )
        row = cur.fetchone()
        conn.close()
        if not row or not row["retrieved_at"]:
            return None

        # Cached snapshot rows loaded at boot are fallbacks, not live API cache hits
        if row["source"] and row["source"].startswith("Live (cached snapshot"):
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
                    "unit": row["unit"] or FACTOR_UNITS.get(factor, ""),
                    "source": row["source"],
                    "resolution": row["resolution"],
                    "data_date": row["data_date"],
                    "retrieved_at": row["retrieved_at"],
                    "transformation": row["transformation"],
                }
        except (ValueError, TypeError):
            return None
    except sqlite3.Error:
        return None
    return None


def cache_feature(
    factor: str,
    lat: float,
    lon: float,
    value: Optional[float],
    unit: str,
    source: str,
    resolution: str,
    data_date: str,
    retrieved_at: str,
    transformation: str,
    db_path: str,
    name: Optional[str] = None,
) -> None:
    """Store retrieved environmental feature in locations and environmental_features tables."""
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
            "SELECT id FROM environmental_features WHERE location_id = ? AND factor = ? LIMIT 1",
            (loc_id, factor),
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
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (loc_id, factor, value, unit, source, resolution, data_date, retrieved_at, transformation),
            )
        conn.commit()
        conn.close()
    except sqlite3.Error:
        pass


def get_cached_rainfall(
    lat: float,
    lon: float,
    db_path: str,
    staleness_hours: int = 24,
) -> Optional[Dict[str, Any]]:
    """Retrieve non-stale cached annual_rainfall feature from SQLite if present."""
    cached = get_cached_feature("annual_rainfall", lat, lon, db_path, staleness_hours=staleness_hours)
    if cached is not None:
        if not cached.get("source"):
            cached["source"] = NASA_POWER_SOURCE
        if not cached.get("resolution"):
            cached["resolution"] = NASA_POWER_RESOLUTION
        if not cached.get("unit"):
            cached["unit"] = "mm/yr"
    return cached


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
    cache_feature(
        factor="annual_rainfall",
        lat=lat,
        lon=lon,
        value=value,
        unit=unit,
        source=source,
        resolution=resolution,
        data_date=data_date,
        retrieved_at=retrieved_at,
        transformation=transformation,
        db_path=db_path,
        name=name,
    )


def fetch_open_meteo_slope(
    lat: float,
    lon: float,
    db_path: Optional[str] = None,
    staleness_hours: int = 24,
    timeout: float = 10.0,
    name: Optional[str] = None,
    snapshots_path: Optional[str] = None,
) -> Tuple[Optional[float], Optional[Dict[str, Any]], Optional[str]]:
    """
    Fetch elevation for target point and 4 neighbouring points ~100m away (north, south, east, west)
    from Open-Meteo elevation API (Copernicus DEM GLO-90) with SQLite caching.
    Calculates ground slope in percent via central difference gradient.

    Returns:
        (slope_percent, metadata_dict, error_warning)
    """
    target_db = db_path or Config.DATABASE_PATH

    # 1. Check cache first
    cached = get_cached_feature("slope", lat, lon, target_db, staleness_hours=staleness_hours)
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

    # 2. Compute 4 neighbouring points approximately 100 m away
    lats, lons = get_slope_sampling_offsets(lat, lon, distance_m=100.0)
    lat_param = ",".join(f"{x:.6f}" for x in lats)
    lon_param = ",".join(f"{y:.6f}" for y in lons)

    params = {
        "latitude": lat_param,
        "longitude": lon_param,
    }

    try:
        resp = _request_with_retry("GET", OPEN_METEO_ELEVATION_URL, params=params, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        elevations = data.get("elevation")

        if not isinstance(elevations, list) or len(elevations) < 5 or any(e is None for e in elevations[:5]):
            raise ValueError("Incomplete elevation array")

        z_center = float(elevations[0])
        z_north = float(elevations[1])
        z_south = float(elevations[2])
        z_east = float(elevations[3])
        z_west = float(elevations[4])

        # Slope in percent via 4-neighbour central difference gradient calculated in gis_processor
        slope_pct = calculate_slope_from_elevations(
            z_center, z_north, z_south, z_east, z_west, distance_m=100.0
        )

        now_iso = datetime.now(timezone.utc).isoformat()
        transformation = (
            "Slope calculated via 4-neighbour central difference gradient: "
            "dz/dx = (elev_east - elev_west) / 200m, "
            "dz/dy = (elev_north - elev_south) / 200m, "
            "slope% = sqrt((dz/dx)^2 + (dz/dy)^2) * 100"
        )

        meta = {
            "unit": "%",
            "source": OPEN_METEO_ELEVATION_SOURCE,
            "resolution": OPEN_METEO_ELEVATION_RESOLUTION,
            "data_date": OPEN_METEO_DATA_DATE,
            "retrieved_at": now_iso,
            "transformation": transformation,
        }

        # Cache in database
        cache_feature(
            factor="slope",
            lat=lat,
            lon=lon,
            value=slope_pct,
            unit="%",
            source=OPEN_METEO_ELEVATION_SOURCE,
            resolution=OPEN_METEO_ELEVATION_RESOLUTION,
            data_date=OPEN_METEO_DATA_DATE,
            retrieved_at=now_iso,
            transformation=transformation,
            db_path=target_db,
            name=name,
        )

        DATA_SOURCES_TELEMETRY["open_meteo"]["last_success"] = now_iso
        DATA_SOURCES_TELEMETRY["open_meteo"]["last_error"] = None
        return slope_pct, meta, None

    except (requests.RequestException, ValueError, KeyError) as exc:
        DATA_SOURCES_TELEMETRY["open_meteo"]["last_error"] = str(exc)
        snapshot = get_saved_snapshot("slope", lat, lon, name, snapshots_path)
        if snapshot is not None and snapshot.get("value") is not None:
            snap_val = snapshot.get("value")
            snap_date = snapshot.get("fetch_date") or snapshot.get("data_date") or "2026-10-22"
            snap_res = snapshot.get("resolution") or OPEN_METEO_ELEVATION_RESOLUTION
            snap_trans = snapshot.get("transformation") or "Retrieved from cached live snapshot"
            now_iso = datetime.now(timezone.utc).isoformat()
            source_label = f"Live (cached snapshot, {snap_date})"
            meta = {
                "unit": "%",
                "source": source_label,
                "resolution": snap_res,
                "data_date": snap_date,
                "retrieved_at": now_iso,
                "transformation": snap_trans,
            }
            return (
                snap_val,
                meta,
                f"Live slope from Open-Meteo was unavailable; used saved snapshot from {snap_date}.",
            )
        return None, None, "Live slope data from Open-Meteo was unavailable; fell back to demo/sample data."


def fetch_nasa_power_rainfall(
    lat: float,
    lon: float,
    db_path: Optional[str] = None,
    staleness_hours: int = 24,
    timeout: float = 10.0,
    name: Optional[str] = None,
    snapshots_path: Optional[str] = None,
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
        resp = _request_with_retry("GET", NASA_POWER_POINT_URL, params=params, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        param_dict = data.get("properties", {}).get("parameter", {}).get("PRECTOTCORR", {})
        ann_daily = param_dict.get("ANN")

        if ann_daily is None or ann_daily < 0:
            raise ValueError("Missing or invalid PRECTOTCORR")

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

        DATA_SOURCES_TELEMETRY["nasa_power"]["last_success"] = now_iso
        DATA_SOURCES_TELEMETRY["nasa_power"]["last_error"] = None
        return ann_yearly, meta, None

    except (requests.RequestException, ValueError, KeyError) as exc:
        DATA_SOURCES_TELEMETRY["nasa_power"]["last_error"] = str(exc)
        snapshot = get_saved_snapshot("annual_rainfall", lat, lon, name, snapshots_path)
        if snapshot is not None and snapshot.get("value") is not None:
            snap_val = snapshot.get("value")
            snap_date = snapshot.get("fetch_date") or snapshot.get("data_date") or "2026-10-22"
            snap_res = snapshot.get("resolution") or NASA_POWER_RESOLUTION
            snap_trans = snapshot.get("transformation") or "Retrieved from cached live snapshot"
            now_iso = datetime.now(timezone.utc).isoformat()
            source_label = f"Live (cached snapshot, {snap_date})"
            meta = {
                "unit": "mm/yr",
                "source": source_label,
                "resolution": snap_res,
                "data_date": snap_date,
                "retrieved_at": now_iso,
                "transformation": snap_trans,
            }
            return (
                snap_val,
                meta,
                f"Live rainfall from NASA POWER was unavailable; used saved snapshot from {snap_date}.",
            )
        return None, None, "Live rainfall data from NASA POWER was unavailable; fell back to demo/sample data."


def fetch_soilgrids_infiltration(
    lat: float,
    lon: float,
    db_path: Optional[str] = None,
    staleness_hours: int = 24,
    timeout: float = 10.0,
    name: Optional[str] = None,
    snapshots_path: Optional[str] = None,
) -> Tuple[Optional[float], Optional[Dict[str, Any]], Optional[str]]:
    """
    Fetch USDA soil texture class from SoilGrids v2.0 REST API and estimate
    saturated hydraulic conductivity (soil_infiltration, mm/hr) using the
    Rawls et al. (1983) lookup table.

    API endpoint: https://rest.isric.org/soilgrids/v2.0/properties/query
    Property requested: TEXCLSS (WRB texture class, 0-30 cm mean)

    Source citation:
        Rawls, W.J., Brakensiek, D.L. & Miller, N. (1983). "Green-Ampt
        infiltration parameters from soil data." J. Hydraulic Engineering,
        109(1), 62-70. https://doi.org/10.1061/(ASCE)0733-9429(1983)109:1(62)

    Returns:
        (infiltration_mm_hr, metadata_dict, error_warning)
    """
    target_db = db_path or Config.DATABASE_PATH

    # 1. Check cache first
    cached = get_cached_feature("soil_infiltration", lat, lon, target_db, staleness_hours=staleness_hours)
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

    # 2. Call SoilGrids REST API for sand, clay, silt properties at 5-15cm depth
    params = [
        ("lon", lon),
        ("lat", lat),
        ("property", "sand"),
        ("property", "clay"),
        ("property", "silt"),
        ("depth", "5-15cm"),
        ("value", "mean"),
    ]
    try:
        resp = _request_with_retry("GET", SOILGRIDS_PROPERTIES_URL, params=params, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()

        layers = data.get("properties", {}).get("layers", [])
        layer_map = {}
        for l in layers:
            if isinstance(l, dict) and l.get("name"):
                layer_map[l["name"].lower()] = l

        fractions: Dict[str, Optional[float]] = {}
        for prop in ("sand", "clay", "silt"):
            layer = layer_map.get(prop)
            if not layer:
                fractions[prop] = None
                continue
            dfactor = float(layer.get("unit_measure", {}).get("d_factor") or 10.0)
            depths = layer.get("depths", [])
            depth_entry = next((d for d in depths if d.get("label") == "5-15cm"), (depths[0] if depths else None))
            if depth_entry:
                val = depth_entry.get("values", {}).get("mean")
                if val is not None and isinstance(val, (int, float)):
                    fractions[prop] = float(val) / dfactor
                else:
                    fractions[prop] = None
            else:
                fractions[prop] = None

        if any(fractions.get(p) is None for p in ("sand", "clay", "silt")):
            DATA_SOURCES_TELEMETRY["soilgrids"]["last_error"] = (
                "SoilGrids returned no sand/clay/silt values at 5-15cm depth (unmeasured or urban sealed surface)"
            )
            snapshot = get_saved_snapshot("soil_infiltration", lat, lon, name, snapshots_path)
            if snapshot is not None and snapshot.get("value") is not None:
                snap_val = snapshot.get("value")
                snap_date = snapshot.get("fetch_date") or snapshot.get("data_date") or "2026-10-22"
                snap_res = snapshot.get("resolution") or SOILGRIDS_RESOLUTION
                snap_trans = snapshot.get("transformation") or "Retrieved from cached live snapshot"
                now_iso = datetime.now(timezone.utc).isoformat()
                source_label = f"Live (cached snapshot, {snap_date})"
                meta = {
                    "unit": "mm/hr",
                    "source": source_label,
                    "resolution": snap_res,
                    "data_date": snap_date,
                    "retrieved_at": now_iso,
                    "transformation": snap_trans,
                }
                return (
                    snap_val,
                    meta,
                    f"Live soil data from SoilGrids returned no sand/clay/silt values at 5-15cm depth; used saved snapshot from {snap_date}.",
                )
            return (
                None,
                None,
                "Live soil data from SoilGrids was unmeasured at coordinates; fell back to demo/sample data.",
            )

        sand_pct = fractions["sand"]
        clay_pct = fractions["clay"]
        silt_pct = fractions["silt"]
        texture_class = classify_usda_texture(sand_pct, silt_pct, clay_pct)
        if not texture_class:
            DATA_SOURCES_TELEMETRY["soilgrids"]["last_error"] = (
                f"SoilGrids fractions ({sand_pct}%, {silt_pct}%, {clay_pct}%) could not be classified into USDA texture"
            )
            snapshot = get_saved_snapshot("soil_infiltration", lat, lon, name, snapshots_path)
            if snapshot is not None and snapshot.get("value") is not None:
                snap_val = snapshot.get("value")
                snap_date = snapshot.get("fetch_date") or snapshot.get("data_date") or "2026-10-22"
                snap_res = snapshot.get("resolution") or SOILGRIDS_RESOLUTION
                snap_trans = snapshot.get("transformation") or "Retrieved from cached live snapshot"
                now_iso = datetime.now(timezone.utc).isoformat()
                source_label = f"Live (cached snapshot, {snap_date})"
                meta = {
                    "unit": "mm/hr",
                    "source": source_label,
                    "resolution": snap_res,
                    "data_date": snap_date,
                    "retrieved_at": now_iso,
                    "transformation": snap_trans,
                }
                return (
                    snap_val,
                    meta,
                    f"SoilGrids fractions could not be classified into USDA texture; used saved snapshot from {snap_date}.",
                )
            return (
                None,
                None,
                "SoilGrids fractions could not be classified into USDA texture; fell back to demo/sample data.",
            )

        ks = infiltration_from_texture(texture_class)
        if ks is None:
            DATA_SOURCES_TELEMETRY["soilgrids"]["last_error"] = (
                f"SoilGrids returned texture class '{texture_class}' not in Rawls table"
            )
            snapshot = get_saved_snapshot("soil_infiltration", lat, lon, name, snapshots_path)
            if snapshot is not None and snapshot.get("value") is not None:
                snap_val = snapshot.get("value")
                snap_date = snapshot.get("fetch_date") or snapshot.get("data_date") or "2026-10-22"
                snap_res = snapshot.get("resolution") or SOILGRIDS_RESOLUTION
                snap_trans = snapshot.get("transformation") or "Retrieved from cached live snapshot"
                now_iso = datetime.now(timezone.utc).isoformat()
                source_label = f"Live (cached snapshot, {snap_date})"
                meta = {
                    "unit": "mm/hr",
                    "source": source_label,
                    "resolution": snap_res,
                    "data_date": snap_date,
                    "retrieved_at": now_iso,
                    "transformation": snap_trans,
                }
                return (
                    snap_val,
                    meta,
                    f"SoilGrids returned texture class '{texture_class}' not in Rawls table; used saved snapshot from {snap_date}.",
                )
            return (
                None,
                None,
                f"SoilGrids returned texture class '{texture_class}' which is not in the "
                "Rawls et al. (1983) lookup table; fell back to demo/sample data.",
            )

        now_iso = datetime.now(timezone.utc).isoformat()
        transformation = (
            f"SoilGrids 5-15cm (sand={sand_pct:.1f}%, silt={silt_pct:.1f}%, clay={clay_pct:.1f}%) → "
            f"USDA texture '{texture_class.title()}' → "
            f"Ks = {ks} mm/hr via Rawls et al. (1983) Table 1 "
            "[DOI: 10.1061/(ASCE)0733-9429(1983)109:1(62)]"
        )

        meta = {
            "unit": "mm/hr",
            "source": SOILGRIDS_SOURCE,
            "resolution": SOILGRIDS_RESOLUTION,
            "data_date": SOILGRIDS_DATA_DATE,
            "retrieved_at": now_iso,
            "transformation": transformation,
        }

        # Cache in database
        cache_feature(
            factor="soil_infiltration",
            lat=lat,
            lon=lon,
            value=ks,
            unit="mm/hr",
            source=SOILGRIDS_SOURCE,
            resolution=SOILGRIDS_RESOLUTION,
            data_date=SOILGRIDS_DATA_DATE,
            retrieved_at=now_iso,
            transformation=transformation,
            db_path=target_db,
            name=name,
        )

        DATA_SOURCES_TELEMETRY["soilgrids"]["last_success"] = now_iso
        DATA_SOURCES_TELEMETRY["soilgrids"]["last_error"] = None
        return ks, meta, None

    except (requests.RequestException, ValueError, KeyError) as exc:
        DATA_SOURCES_TELEMETRY["soilgrids"]["last_error"] = str(exc)
        snapshot = get_saved_snapshot("soil_infiltration", lat, lon, name, snapshots_path)
        if snapshot is not None and snapshot.get("value") is not None:
            snap_val = snapshot.get("value")
            snap_date = snapshot.get("fetch_date") or snapshot.get("data_date") or "2026-10-22"
            snap_res = snapshot.get("resolution") or SOILGRIDS_RESOLUTION
            snap_trans = snapshot.get("transformation") or "Retrieved from cached live snapshot"
            now_iso = datetime.now(timezone.utc).isoformat()
            source_label = f"Live (cached snapshot, {snap_date})"
            meta = {
                "unit": "mm/hr",
                "source": source_label,
                "resolution": snap_res,
                "data_date": snap_date,
                "retrieved_at": now_iso,
                "transformation": snap_trans,
            }
            return (
                snap_val,
                meta,
                f"Live soil data from SoilGrids timed out; used saved snapshot from {snap_date}.",
            )
        return (
            None,
            None,
            "Live soil data from SoilGrids was unavailable; fell back to demo/sample data.",
        )


def fetch_osm_open_space(
    lat: float,
    lon: float,
    db_path: Optional[str] = None,
    staleness_hours: int = 24,
    timeout: float = 10.0,
    radius_m: int = OSM_OPEN_SPACE_RADIUS_M,
    name: Optional[str] = None,
    snapshots_path: Optional[str] = None,
) -> Tuple[Optional[float], Optional[Dict[str, Any]], Optional[str]]:
    """
    Query OpenStreetMap Overpass API for parks / green spaces within `radius_m`
    metres of the target point. Tries Overpass mirrors sequentially.

    Returns:
        (1.0 if any open space found, 0.0 if none, metadata_dict, error_warning)
    """
    target_db = db_path or Config.DATABASE_PATH

    # 1. Check cache
    cached = get_cached_feature("open_space", lat, lon, target_db, staleness_hours=staleness_hours)
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

    # 2. Build Overpass QL query for parks, gardens, forests, grass areas
    overpass_query = (
        f"[out:json][timeout:{int(timeout)}];"
        f"("
        f'way["leisure"~"park|garden|nature_reserve|recreation_ground"]'
        f"(around:{radius_m},{lat},{lon});"
        f'relation["leisure"~"park|garden|nature_reserve|recreation_ground"]'
        f"(around:{radius_m},{lat},{lon});"
        f'way["landuse"~"grass|forest|meadow|village_green"]'
        f"(around:{radius_m},{lat},{lon});"
        f");"
        f"out count;"
    )

    success = False
    open_space_val = None
    meta = None

    for mirror_url in OVERPASS_MIRRORS:
        try:
            req_timeout = (5.0, float(timeout)) if isinstance(timeout, (int, float)) else (5.0, 5.0)
            resp = _request_with_retry(
                "POST",
                mirror_url,
                data={"data": overpass_query},
                retries=1,
                connect_timeout=5.0,
                timeout=req_timeout,
            )
            resp.raise_for_status()
            data = resp.json()

            total_count = data.get("elements", [])
            count_elements = [
                e for e in total_count
                if isinstance(e, dict) and e.get("type") == "count"
            ]
            if count_elements:
                tags = count_elements[0].get("tags", {})
                total = int(tags.get("total", 0))
            else:
                total = len(total_count)

            open_space_val = 1.0 if total > 0 else 0.0
            now_iso = datetime.now(timezone.utc).isoformat()
            transformation = (
                f"Overpass QL query: leisure/landuse parks and green areas "
                f"within {radius_m}m radius; result = {'present' if open_space_val else 'absent'} "
                f"({total} feature(s) found via {mirror_url})"
            )

            meta = {
                "unit": "binary (1=present, 0=absent)",
                "source": OSM_SOURCE,
                "resolution": OSM_RESOLUTION,
                "data_date": OSM_DATA_DATE,
                "retrieved_at": now_iso,
                "transformation": transformation,
            }

            cache_feature(
                factor="open_space",
                lat=lat,
                lon=lon,
                value=open_space_val,
                unit="binary (1=present, 0=absent)",
                source=OSM_SOURCE,
                resolution=OSM_RESOLUTION,
                data_date=OSM_DATA_DATE,
                retrieved_at=now_iso,
                transformation=transformation,
                db_path=target_db,
                name=name,
            )

            DATA_SOURCES_TELEMETRY["overpass"]["last_success"] = now_iso
            DATA_SOURCES_TELEMETRY["overpass"]["last_error"] = None
            success = True
            break
        except (requests.RequestException, ValueError, KeyError):
            continue

    if success and meta is not None:
        return open_space_val, meta, None

    DATA_SOURCES_TELEMETRY["overpass"]["last_error"] = "All Overpass mirrors timed out or failed (>5s connect)"
    # Fallback to saved snapshot
    snapshot = get_saved_snapshot("open_space", lat, lon, name, snapshots_path)
    if snapshot is not None and snapshot.get("value") is not None:
        snap_val = snapshot.get("value")
        snap_date = snapshot.get("fetch_date") or snapshot.get("data_date") or "2026-10-22"
        snap_res = snapshot.get("resolution") or OSM_RESOLUTION
        snap_trans = snapshot.get("transformation") or "Retrieved from cached live snapshot"
        now_iso = datetime.now(timezone.utc).isoformat()
        source_label = f"Live (cached snapshot, {snap_date})"
        meta = {
            "unit": "binary (1=present, 0=absent)",
            "source": source_label,
            "resolution": snap_res,
            "data_date": snap_date,
            "retrieved_at": now_iso,
            "transformation": snap_trans,
        }
        return (
            snap_val,
            meta,
            f"Live open_space data from OpenStreetMap mirrors timed out; used saved snapshot from {snap_date}.",
        )

    return (
        None,
        None,
        "Live open_space data from OpenStreetMap was unavailable; fell back to demo/sample data.",
    )


def fetch_osm_building_distance(
    lat: float,
    lon: float,
    db_path: Optional[str] = None,
    staleness_hours: int = 24,
    timeout: float = 10.0,
    radius_m: int = OSM_BUILDING_RADIUS_M,
    name: Optional[str] = None,
    snapshots_path: Optional[str] = None,
) -> Tuple[Optional[float], Optional[Dict[str, Any]], Optional[str]]:
    """
    Query OpenStreetMap Overpass API for buildings within `radius_m` metres and
    return the distance to the nearest building centroid in metres. Tries Overpass
    mirrors sequentially in order.

    Centroid approximation: the midpoint of the bounding box returned by
    Overpass for each way. Distance computed via haversine formula.

    Returns:
        (distance_m or None, metadata_dict, error_warning)
    """
    target_db = db_path or Config.DATABASE_PATH

    # 1. Check cache
    cached = get_cached_feature("building_distance", lat, lon, target_db, staleness_hours=staleness_hours)
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

    # 2. Build Overpass QL query for buildings
    overpass_query = (
        f"[out:json][timeout:{int(timeout)}];"
        f'way["building"](around:{radius_m},{lat},{lon});'
        f"out bb;"
    )

    success = False
    dist_m = None
    meta = None

    for mirror_url in OVERPASS_MIRRORS:
        try:
            req_timeout = (5.0, float(timeout)) if isinstance(timeout, (int, float)) else (5.0, 5.0)
            resp = _request_with_retry(
                "POST",
                mirror_url,
                data={"data": overpass_query},
                retries=1,
                connect_timeout=5.0,
                timeout=req_timeout,
            )
            resp.raise_for_status()
            data = resp.json()

            elements = data.get("elements", [])
            buildings = [e for e in elements if isinstance(e, dict) and e.get("type") == "way"]

            if not buildings:
                dist_m = float(radius_m)
                found_count = 0
            else:
                min_dist_m = float("inf")
                for bldg in buildings:
                    bounds = bldg.get("bounds")
                    if not bounds:
                        continue
                    c_lat = (bounds["minlat"] + bounds["maxlat"]) / 2.0
                    c_lon = (bounds["minlon"] + bounds["maxlon"]) / 2.0
                    d_km = haversine_distance(lat, lon, c_lat, c_lon)
                    d_m = d_km * 1000.0
                    if d_m < min_dist_m:
                        min_dist_m = d_m
                dist_m = round(min_dist_m, 1) if min_dist_m < float("inf") else float(radius_m)
                found_count = len(buildings)

            now_iso = datetime.now(timezone.utc).isoformat()
            transformation = (
                f"Nearest building centroid (bounding-box midpoint) from {found_count} "
                f"OSM way[building] features within {radius_m}m via {mirror_url}; haversine distance = {dist_m}m"
            )

            meta = {
                "unit": "m",
                "source": OSM_SOURCE,
                "resolution": OSM_RESOLUTION,
                "data_date": OSM_DATA_DATE,
                "retrieved_at": now_iso,
                "transformation": transformation,
            }

            cache_feature(
                factor="building_distance",
                lat=lat,
                lon=lon,
                value=dist_m,
                unit="m",
                source=OSM_SOURCE,
                resolution=OSM_RESOLUTION,
                data_date=OSM_DATA_DATE,
                retrieved_at=now_iso,
                transformation=transformation,
                db_path=target_db,
                name=name,
            )

            DATA_SOURCES_TELEMETRY["overpass"]["last_success"] = now_iso
            DATA_SOURCES_TELEMETRY["overpass"]["last_error"] = None
            success = True
            break
        except (requests.RequestException, ValueError, KeyError):
            continue

    if success and meta is not None:
        return dist_m, meta, None

    DATA_SOURCES_TELEMETRY["overpass"]["last_error"] = "All Overpass mirrors timed out or failed (>5s connect)"
    # Fallback to saved snapshot
    snapshot = get_saved_snapshot("building_distance", lat, lon, name, snapshots_path)
    if snapshot is not None and snapshot.get("value") is not None:
        snap_val = snapshot.get("value")
        snap_date = snapshot.get("fetch_date") or snapshot.get("data_date") or "2026-10-22"
        snap_res = snapshot.get("resolution") or OSM_RESOLUTION
        snap_trans = snapshot.get("transformation") or "Retrieved from cached live snapshot"
        now_iso = datetime.now(timezone.utc).isoformat()
        source_label = f"Live (cached snapshot, {snap_date})"
        meta = {
            "unit": "m",
            "source": source_label,
            "resolution": snap_res,
            "data_date": snap_date,
            "retrieved_at": now_iso,
            "transformation": snap_trans,
        }
        return (
            snap_val,
            meta,
            f"Live building_distance data from OpenStreetMap mirrors timed out; used saved snapshot from {snap_date}.",
        )

    return (
        None,
        None,
        "Live building_distance data from OpenStreetMap was unavailable; fell back to demo/sample data.",
    )


# OpenStreetMap Nominatim Geocoding configuration
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_USER_AGENT = "ADAPTFIT/1.0 (Climate Adaptation Transferability Tool; https://github.com/adaptfit)"

_nominatim_lock = threading.Lock()
_last_nominatim_request_time = 0.0


def _rate_limit_nominatim() -> None:
    """Enforce maximum 1 request per second to comply with Nominatim Usage Policy."""
    global _last_nominatim_request_time
    with _nominatim_lock:
        now = time.time()
        elapsed = now - _last_nominatim_request_time
        if elapsed < 1.0:
            time.sleep(1.0 - elapsed)
        _last_nominatim_request_time = time.time()


def geocode_place(
    query: str,
    db_path: Optional[str] = None,
    timeout: float = 8.0,
) -> List[Dict[str, Any]]:
    """
    Search place name using OpenStreetMap Nominatim API with SQLite caching,
    strict 1 req/s rate limiting, and graceful offline/error fallback to sample data.
    """
    if not query or not query.strip():
        return []

    q_clean = query.strip()
    q_norm = q_clean.lower()
    target_db = db_path or Config.DATABASE_PATH

    # 1. Ensure geocoding_cache table exists and check SQLite cache
    conn = None
    try:
        conn = sqlite3.connect(target_db, timeout=30.0)
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS geocoding_cache (
                query TEXT PRIMARY KEY,
                results_json TEXT NOT NULL,
                retrieved_at TEXT NOT NULL
            )
            """
        )
        cur = conn.cursor()
        cur.execute("SELECT results_json FROM geocoding_cache WHERE query = ?", (q_norm,))
        row = cur.fetchone()
        if row:
            conn.close()
            return json.loads(row[0])
    except Exception:
        conn = None

    # 2. Rate-limit and query Nominatim
    results: List[Dict[str, Any]] = []
    try:
        _rate_limit_nominatim()
        headers = {"User-Agent": _get_user_agent()}
        params = {
            "q": q_clean,
            "format": "json",
            "limit": 5,
            "addressdetails": 1,
        }
        req_timeout = (5.0, float(timeout)) if isinstance(timeout, (int, float)) else timeout
        resp = requests.get(NOMINATIM_URL, params=params, headers=headers, timeout=req_timeout)
        resp.raise_for_status()
        data = resp.json()

        if isinstance(data, list):
            for item in data:
                try:
                    display_name = item.get("display_name", "")
                    short_name = item.get("name") or (display_name.split(",")[0] if display_name else q_clean)
                    results.append({
                        "name": short_name,
                        "display_name": display_name,
                        "latitude": round(float(item["lat"]), 4),
                        "longitude": round(float(item["lon"]), 4),
                        "type": item.get("type"),
                        "importance": item.get("importance"),
                    })
                except (KeyError, ValueError, TypeError):
                    continue
    except Exception:
        # Graceful fallback: check local sample_environmental_data.csv
        sample_locs = load_sample_locations()
        for loc in sample_locs:
            if q_norm in loc["name"].lower():
                results.append({
                    "name": loc["name"],
                    "display_name": f"{loc['name']}, Maharashtra, India",
                    "latitude": round(float(loc["latitude"]), 4),
                    "longitude": round(float(loc["longitude"]), 4),
                    "type": "sample_location",
                    "importance": 0.5,
                })

    # 3. Store results in cache if connection active
    if conn:
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            cur = conn.cursor()
            cur.execute(
                "INSERT OR REPLACE INTO geocoding_cache (query, results_json, retrieved_at) VALUES (?, ?, ?)",
                (q_norm, json.dumps(results), now_iso),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

    return results


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
    use_live_slope: Optional[bool] = None,
    use_live_soil: Optional[bool] = None,
    use_live_osm: Optional[bool] = None,
    db_path: Optional[str] = None,
    staleness_hours: Optional[int] = None,
    snapshots_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Fetch environmental values and metadata for a given coordinate or location name.
    
    If use_live_rainfall is True, annual_rainfall is fetched from NASA POWER.
    If use_live_slope is True, slope is fetched from Open-Meteo elevation.
    If use_live_soil is True, soil_infiltration is fetched from SoilGrids (or cached snapshot).
    If use_live_osm is True, open_space and building_distance are fetched from Overpass mirrors (or cached snapshot).
    All other factors stay from the CSV (or fall back to snapshot, then CSV demo data).
    When all live flags are False, behaviour is exactly as default (CSV only).
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

    if use_live_slope is None:
        try:
            from flask import current_app
            if current_app:
                use_live_slope = current_app.config.get("USE_LIVE_SLOPE", False)
            else:
                use_live_slope = getattr(Config, "USE_LIVE_SLOPE", False)
        except (RuntimeError, ImportError):
            use_live_slope = getattr(Config, "USE_LIVE_SLOPE", False)

    if use_live_soil is None:
        try:
            from flask import current_app
            if current_app:
                use_live_soil = current_app.config.get("USE_LIVE_SOIL", False)
            else:
                use_live_soil = getattr(Config, "USE_LIVE_SOIL", False)
        except (RuntimeError, ImportError):
            use_live_soil = getattr(Config, "USE_LIVE_SOIL", False)

    if use_live_osm is None:
        try:
            from flask import current_app
            if current_app:
                use_live_osm = current_app.config.get("USE_LIVE_OSM", False)
            else:
                use_live_osm = getattr(Config, "USE_LIVE_OSM", False)
        except (RuntimeError, ImportError):
            use_live_osm = getattr(Config, "USE_LIVE_OSM", False)

    def _parse_bool(v: Any) -> bool:
        if isinstance(v, str):
            return v.strip().lower() in ("true", "1", "yes")
        return bool(v)

    use_live_rainfall = _parse_bool(use_live_rainfall)
    use_live_slope = _parse_bool(use_live_slope)
    use_live_soil = _parse_bool(use_live_soil)
    use_live_osm = _parse_bool(use_live_osm)

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
            snapshots_path=snapshots_path,
        )
        if live_meta is not None:
            values["annual_rainfall"] = live_val
            metadata["annual_rainfall"] = live_meta
            if live_meta.get("source", "").startswith("Live (cached snapshot"):
                live_rainfall_used = False
            else:
                live_rainfall_used = (live_val is not None)
            if live_warn:
                warnings.append(live_warn)
        else:
            # Fallback to CSV value (already in values["annual_rainfall"])
            if live_warn:
                warnings.append(live_warn)
            if matched_record and values.get("annual_rainfall") is not None:
                metadata["annual_rainfall"]["source"] = DEMO_SOURCE
            live_rainfall_used = False

    # If live slope flag is enabled: fetch Open-Meteo elevation for slope
    live_slope_used = False
    if use_live_slope:
        live_slope_val, live_slope_meta, live_slope_warn = fetch_open_meteo_slope(
            lat=lat,
            lon=lon,
            db_path=db_path,
            staleness_hours=staleness_hours,
            timeout=10.0,
            name=name or (matched_record.get("name") if matched_record else None),
            snapshots_path=snapshots_path,
        )
        if live_slope_meta is not None:
            values["slope"] = live_slope_val
            metadata["slope"] = live_slope_meta
            if live_slope_meta.get("source", "").startswith("Live (cached snapshot"):
                live_slope_used = False
            else:
                live_slope_used = (live_slope_val is not None)
            if live_slope_warn:
                warnings.append(live_slope_warn)
        else:
            # Fallback to CSV value (already in values["slope"])
            if live_slope_warn:
                warnings.append(live_slope_warn)
            if matched_record and values.get("slope") is not None:
                metadata["slope"]["source"] = DEMO_SOURCE
            live_slope_used = False

    # If live soil flag is enabled: fetch SoilGrids texture → infiltration estimate
    live_soil_used = False
    if use_live_soil:
        live_soil_val, live_soil_meta, live_soil_warn = fetch_soilgrids_infiltration(
            lat=lat,
            lon=lon,
            db_path=db_path,
            staleness_hours=staleness_hours,
            timeout=10.0,
            name=name or (matched_record.get("name") if matched_record else None),
            snapshots_path=snapshots_path,
        )
        if live_soil_meta is not None:
            values["soil_infiltration"] = live_soil_val
            metadata["soil_infiltration"] = live_soil_meta
            if live_soil_meta.get("source", "").startswith("Live (cached snapshot"):
                live_soil_used = False
            else:
                live_soil_used = (live_soil_val is not None)
            if live_soil_warn:
                warnings.append(live_soil_warn)
        else:
            # Fallback to CSV value (already in values["soil_infiltration"])
            if live_soil_warn:
                warnings.append(live_soil_warn)
            if matched_record and values.get("soil_infiltration") is not None:
                metadata["soil_infiltration"]["source"] = DEMO_SOURCE
            live_soil_used = False

    # If live OSM flag is enabled: fetch open_space and building_distance from Overpass
    live_osm_used = False
    if use_live_osm:
        loc_name_hint = name or (matched_record.get("name") if matched_record else None)

        live_osm_os = False
        live_osm_bd = False

        # open_space
        osm_os_val, osm_os_meta, osm_os_warn = fetch_osm_open_space(
            lat=lat,
            lon=lon,
            db_path=db_path,
            staleness_hours=staleness_hours,
            timeout=10.0,
            name=loc_name_hint,
            snapshots_path=snapshots_path,
        )
        if osm_os_meta is not None:
            values["open_space"] = osm_os_val
            metadata["open_space"] = osm_os_meta
            if not osm_os_meta.get("source", "").startswith("Live (cached snapshot"):
                live_osm_os = True
            if osm_os_warn:
                warnings.append(osm_os_warn)
        else:
            if osm_os_warn:
                warnings.append(osm_os_warn)
            if matched_record and values.get("open_space") is not None:
                metadata["open_space"]["source"] = DEMO_SOURCE

        # building_distance
        osm_bd_val, osm_bd_meta, osm_bd_warn = fetch_osm_building_distance(
            lat=lat,
            lon=lon,
            db_path=db_path,
            staleness_hours=staleness_hours,
            timeout=10.0,
            name=loc_name_hint,
            snapshots_path=snapshots_path,
        )
        if osm_bd_meta is not None:
            values["building_distance"] = osm_bd_val
            metadata["building_distance"] = osm_bd_meta
            if not osm_bd_meta.get("source", "").startswith("Live (cached snapshot"):
                live_osm_bd = True
            if osm_bd_warn:
                warnings.append(osm_bd_warn)
        else:
            if osm_bd_warn:
                warnings.append(osm_bd_warn)
            if matched_record and values.get("building_distance") is not None:
                metadata["building_distance"]["source"] = DEMO_SOURCE

        live_osm_used = bool(live_osm_os and live_osm_bd)

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
        "live_slope_used": live_slope_used,
        "live_soil_used": live_soil_used,
        "live_osm_used": live_osm_used,
    }
