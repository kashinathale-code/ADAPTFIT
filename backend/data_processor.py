"""
ADAPTFIT Data Processor
=======================
Coordinate validation, unit checks, missingness handling,
and source/resolution data quality warning generation.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


def validate_coordinates(lat: Any, lon: Any) -> Tuple[float, float]:
    """
    Validate and return (latitude, longitude) as floats.
    Raises ValueError on missing, non-numeric, or out-of-bounds coordinates.
    Latitude must be in [-90, 90], Longitude in [-180, 180].
    """
    if lat is None or lon is None:
        raise ValueError("Latitude and longitude are both required.")

    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (ValueError, TypeError):
        raise ValueError("Latitude and longitude must be valid floating-point numbers.")

    if not (-90.0 <= lat_f <= 90.0):
        raise ValueError(
            f"Latitude {lat_f} is out of bounds; must be between -90 and 90 degrees."
        )

    if not (-180.0 <= lon_f <= 180.0):
        raise ValueError(
            f"Longitude {lon_f} is out of bounds; must be between -180 and 180 degrees."
        )

    return lat_f, lon_f


def clean_environmental_value(val: Any) -> Optional[float]:
    """Clean and cast an environmental factor value to float, returning None if missing."""
    if val is None:
        return None
    val_str = str(val).strip()
    if not val_str or val_str.lower() in ("null", "none", "nan", ""):
        return None
    try:
        return float(val_str)
    except (ValueError, TypeError):
        return None


def generate_metadata_warnings(
    factors_metadata: Dict[str, Dict[str, Any]],
    location_label: str = "Location",
) -> List[str]:
    """
    Generate data quality warnings for source, resolution, and data gaps.
    Produces warnings matching TRD §7 ("Soil data is ~250 m resolution; verify infiltration on site.").
    """
    warnings: List[str] = []

    for factor, meta in factors_metadata.items():
        res = meta.get("resolution")
        src = meta.get("source")
        factor_title = factor.replace("_", " ").title()

        # Coarse resolution check (e.g., SoilGrids ~250m)
        if res and ("250" in str(res) or "km" in str(res).lower()):
            warnings.append(
                f"{factor_title} data for {location_label} is {res} resolution; "
                "verify on site."
            )

        # Illustrative or unverified sample source check
        if src and ("sample" in str(src).lower() or "illustrative" in str(src).lower()):
            warnings.append(
                f"{factor_title} data for {location_label} uses unverified sample data ({src})."
            )

    return warnings
