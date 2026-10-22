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


def test_generate_metadata_warnings_resolution_numerical():
    # 250 m should trigger coarse resolution warning
    meta_250 = {
        "soil_infiltration": {"resolution": "250 m", "source": "SoilGrids"},
    }
    warn_250 = generate_metadata_warnings(meta_250, location_label="Site B")
    assert any("250 m resolution" in w for w in warn_250)

    # 1250 m should NOT trigger coarse resolution warning for 250 m
    meta_1250 = {
        "soil_infiltration": {"resolution": "1250 m", "source": "Local Survey"},
    }
    warn_1250 = generate_metadata_warnings(meta_1250, location_label="Site B")
    assert not any("resolution" in w for w in warn_1250)

    # ~250m should match
    meta_tilde = {
        "soil_infiltration": {"resolution": "~250m", "source": "SoilGrids"},
    }
    warn_tilde = generate_metadata_warnings(meta_tilde, location_label="Site B")
    assert any("~250m resolution" in w for w in warn_tilde)

    # 50 km should match coarse resolution check
    meta_km = {
        "annual_rainfall": {"resolution": "50 km", "source": "NASA POWER"},
    }
    warn_km = generate_metadata_warnings(meta_km, location_label="Site B")
    assert any("50 km resolution" in w for w in warn_km)


def test_generate_rainfall_grid_warning():
    from backend.data_processor import generate_rainfall_grid_warning

    # Both reference and target use NASA POWER
    warn = generate_rainfall_grid_warning("NASA POWER (POWER API)", "NASA POWER (POWER API)")
    assert warn is not None
    assert "~0.5 degree (~50 km) grid" in warn
    assert "regional context" in warn

    # Only one uses NASA POWER
    warn_single = generate_rainfall_grid_warning("NASA POWER (POWER API)", "Sample CSV")
    assert warn_single is None

    # Neither uses NASA POWER
    warn_none = generate_rainfall_grid_warning("Sample CSV", "Demo")
    assert warn_none is None


def test_gis_processor_slope():
    from backend.gis_processor import calculate_slope_from_elevations, get_slope_sampling_offsets

    # Flat ground: center=100, north=100, south=100, east=100, west=100 -> 0.0%
    slope_flat = calculate_slope_from_elevations(100.0, 100.0, 100.0, 100.0, 100.0, distance_m=100.0)
    assert slope_flat == 0.0

    # East-West slope: east=110, west=90 (delta=20m across 200m -> 10% slope)
    slope_east = calculate_slope_from_elevations(100.0, 100.0, 100.0, 110.0, 90.0, distance_m=100.0)
    assert slope_east == 10.0

    # Sampling offsets
    lats, lons = get_slope_sampling_offsets(18.52, 73.85, distance_m=100.0)
    assert len(lats) == 5
    assert len(lons) == 5
    assert lats[0] == 18.52
    assert lons[0] == 73.85
