"""
Unit tests for data_fetcher and data_processor modules.
"""

import os
import pytest

from backend.data_fetcher import (
    haversine_distance,
    load_sample_locations,
    fetch_location_environmental_data,
)
from backend.data_processor import (
    clean_environmental_value,
    generate_metadata_warnings,
    validate_coordinates,
)


def test_haversine_distance():
    # Distance between Pune (18.5204, 73.8567) and Lonavala (18.7557, 73.4091) is ~53 km
    dist = haversine_distance(18.5204, 73.8567, 18.7557, 73.4091)
    assert 50.0 < dist < 60.0


def test_load_sample_locations():
    locations = load_sample_locations()
    assert len(locations) >= 5
    names = {loc["name"] for loc in locations}
    assert "Pimpri" in names
    assert "Pune city" in names
    assert "Nashik city" in names
    assert "Niphad" in names
    assert "Lonavala" in names

    # Verify that missing values are properly stored as None (e.g. soil_infiltration at Lonavala)
    lonavala = next(loc for loc in locations if loc["name"] == "Lonavala")
    assert lonavala["factors"]["soil_infiltration"] is None

    # Verify that present values are parsed as floats
    pune = next(loc for loc in locations if loc["name"] == "Pune city")
    assert pune["factors"]["annual_rainfall"] == 740.0
    assert pune["factors"]["slope"] == 3.0


def test_fetch_location_environmental_data_nearest():
    # Coords close to Pune city
    res = fetch_location_environmental_data(18.52, 73.85)
    assert res["matched_sample_location"] == "Pune city"
    assert res["distance_km"] < 2.0
    assert res["values"]["annual_rainfall"] == 740.0
    assert res["values"]["slope"] == 3.0


def test_fetch_location_environmental_data_outside_coverage():
    # Coords far away (e.g. Delhi: 28.6139, 77.2090)
    res = fetch_location_environmental_data(28.6139, 77.2090, max_distance_km=50.0)
    assert res["matched_sample_location"] is None
    assert any("outside sample dataset coverage" in w for w in res["warnings"])


def test_validate_coordinates():
    # Valid
    lat, lon = validate_coordinates("19.10", "73.00")
    assert lat == 19.10
    assert lon == 73.00

    # Missing
    with pytest.raises(ValueError, match="required"):
        validate_coordinates(None, 73.0)

    # Non-numeric
    with pytest.raises(ValueError, match="floating-point"):
        validate_coordinates("invalid", 73.0)

    # Out of range
    with pytest.raises(ValueError, match="Latitude"):
        validate_coordinates(95.0, 73.0)

    with pytest.raises(ValueError, match="Longitude"):
        validate_coordinates(18.5, 185.0)


def test_clean_environmental_value():
    assert clean_environmental_value(None) is None
    assert clean_environmental_value("") is None
    assert clean_environmental_value("NaN") is None
    assert clean_environmental_value("null") is None
    assert clean_environmental_value("12.5") == 12.5
    assert clean_environmental_value(30) == 30.0


def test_generate_metadata_warnings():
    meta = {
        "soil_infiltration": {"resolution": "250 m", "source": "SoilGrids"},
        "slope": {"resolution": "30 m", "source": "DEM illustrative"},
    }
    warnings = generate_metadata_warnings(meta, location_label="Site B")
    warnings_str = " ".join(warnings).lower()
    assert "250 m" in warnings_str
    assert "illustrative" in warnings_str
