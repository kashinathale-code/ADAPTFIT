"""
ADAPTFIT Data Fetcher
=====================
Reads environmental data from datasets/sample_environmental_data.csv
and returns values with source, resolution, and units, with missing
values represented strictly as None (null in JSON).
"""

from __future__ import annotations

import csv
import math
import os
from typing import Any, Dict, List, Optional

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
) -> Dict[str, Any]:
    """
    Fetch environmental values and metadata for a given coordinate or location name.
    
    If the location matches or is near a record in sample_environmental_data.csv,
    returns its factors, source and resolution. Missing values remain None (null).
    """
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
        rec_source = matched_record.get("source")
        rec_res = matched_record.get("resolution")
        rec_date = matched_record.get("data_date")

        for k in FACTOR_KEYS:
            val = matched_record["factors"].get(k)
            values[k] = val
            metadata[k] = {
                "unit": FACTOR_UNITS.get(k, ""),
                "source": rec_source,
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

    return {
        "name": name or (matched_record.get("name") if matched_record else None),
        "latitude": lat,
        "longitude": lon,
        "matched_sample_location": matched_record.get("name") if matched_record else None,
        "distance_km": min_dist,
        "values": values,
        "metadata": metadata,
        "warnings": warnings,
    }
