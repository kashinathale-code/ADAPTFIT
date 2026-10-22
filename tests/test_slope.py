"""
Tests for Live Open-Meteo Copernicus DEM slope integration, caching, fallback, and configuration flag.
All HTTP calls are strictly mocked with no real network access.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
import pytest
import requests
import sqlite3

from app import create_app
from backend.data_fetcher import (
    OPEN_METEO_ELEVATION_RESOLUTION,
    OPEN_METEO_ELEVATION_SOURCE,
    DEMO_SOURCE,
    fetch_location_environmental_data,
    fetch_open_meteo_slope,
)
from database.seed import seed


@pytest.fixture
def test_db(tmp_path):
    """Create a temporary initialized SQLite database."""
    db_file = str(tmp_path / "test_slope.db")
    seed(db_path=db_file)
    return db_file


def _mock_elevation_response(elevations=None):
    """
    Return a mock requests.Response with valid Open-Meteo elevation JSON.
    Default elevations: center=100.0, north=104.0, south=100.0, east=106.0, west=100.0
    dz/dx = (106 - 100) / 200 = 0.03
    dz/dy = (104 - 100) / 200 = 0.02
    gradient = sqrt(0.03^2 + 0.02^2) = sqrt(0.0013) ≈ 0.0360555 -> 3.6%
    """
    if elevations is None:
        elevations = [100.0, 104.0, 100.0, 106.0, 100.0]
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "elevation": elevations
    }
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


def test_flag_off_behaviour(test_db):
    """When USE_LIVE_SLOPE is false, behaviour is exactly as default (CSV only, no HTTP call)."""
    with patch("requests.get") as mock_get:
        res = fetch_location_environmental_data(
            18.5204,
            73.8567,
            use_live_slope=False,
            db_path=test_db,
        )
        mock_get.assert_not_called()
        assert res["values"]["slope"] == 3.0
        assert res["metadata"]["slope"]["source"] == DEMO_SOURCE
        assert res["metadata"]["slope"]["resolution"] == "n/a (demo)"
        assert res["values"]["annual_rainfall"] == 740.0
        assert res["live_slope_used"] is False


def test_live_slope_success_and_calculation(test_db):
    """
    When USE_LIVE_SLOPE is true, calls Open-Meteo elevation API for target and 4 neighbours,
    calculates ground slope % via 4-neighbour central difference gradient, and keeps other factors from CSV.
    """
    with patch("requests.get", return_value=_mock_elevation_response()) as mock_get:
        res = fetch_location_environmental_data(
            18.5204,
            73.8567,
            use_live_slope=True,
            db_path=test_db,
        )
        assert mock_get.called
        args, kwargs = mock_get.call_args
        assert "api.open-meteo.com/v1/elevation" in args[0]
        assert kwargs.get("timeout") == 10.0
        params = kwargs.get("params", {})
        assert "latitude" in params
        assert "longitude" in params
        lats = params["latitude"].split(",")
        lons = params["longitude"].split(",")
        assert len(lats) == 5
        assert len(lons) == 5

        # Center point matches query coordinates
        assert abs(float(lats[0]) - 18.5204) < 1e-4
        assert abs(float(lons[0]) - 73.8567) < 1e-4

        # Slope calculation verification: 3.6%
        assert res["values"]["slope"] == 3.6
        meta = res["metadata"]["slope"]
        assert meta["source"] == OPEN_METEO_ELEVATION_SOURCE
        assert meta["unit"] == "%"
        assert meta["resolution"] == OPEN_METEO_ELEVATION_RESOLUTION
        assert "90m" in meta["resolution"]
        assert "Copernicus DEM" in meta["resolution"]
        assert "4-neighbour" in meta["transformation"]
        assert res["live_slope_used"] is True

        # Other factors remain strictly from CSV
        assert res["values"]["annual_rainfall"] == 740.0
        assert res["values"]["soil_infiltration"] == 22.0
        assert res["values"]["open_space"] == 1.0
        assert res["values"]["building_distance"] == 6.0
        assert res["metadata"]["annual_rainfall"]["source"] == DEMO_SOURCE


def test_live_slope_cached_in_db(test_db):
    """Verify calculated slope is stored in environmental_features table."""
    with patch("requests.get", return_value=_mock_elevation_response()):
        fetch_location_environmental_data(
            18.5204,
            73.8567,
            use_live_slope=True,
            db_path=test_db,
        )

    conn = sqlite3.connect(test_db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        """
        SELECT ef.factor, ef.value, ef.unit, ef.source, ef.resolution, ef.transformation, ef.retrieved_at
        FROM environmental_features ef
        JOIN locations l ON ef.location_id = l.id
        WHERE ef.factor = 'slope'
        """
    )
    row = cur.fetchone()
    conn.close()

    assert row is not None
    assert row["value"] == 3.6
    assert row["unit"] == "%"
    assert row["source"] == OPEN_METEO_ELEVATION_SOURCE
    assert "90m" in row["resolution"]
    assert "Copernicus DEM" in row["resolution"]
    assert row["retrieved_at"] is not None
    assert "central difference" in row["transformation"]


def test_cache_reuse_within_staleness_hours(test_db):
    """Second call reuses cached slope without issuing another HTTP request."""
    with patch("requests.get", return_value=_mock_elevation_response()) as mock_get:
        # First call -> fetches and caches
        res1 = fetch_location_environmental_data(
            18.5204,
            73.8567,
            use_live_slope=True,
            db_path=test_db,
            staleness_hours=24,
        )
        assert mock_get.call_count == 1
        assert res1["values"]["slope"] == 3.6

        # Second call -> cache hit
        res2 = fetch_location_environmental_data(
            18.5204,
            73.8567,
            use_live_slope=True,
            db_path=test_db,
            staleness_hours=24,
        )
        assert mock_get.call_count == 1  # Not called again
        assert res2["values"]["slope"] == 3.6
        assert res2["metadata"]["slope"]["source"] == OPEN_METEO_ELEVATION_SOURCE


def test_stale_cache_refreshes(test_db):
    """When cached entry is older than CACHE_STALENESS_HOURS, refreshes via Open-Meteo API."""
    with patch("requests.get", return_value=_mock_elevation_response()) as mock_get:
        fetch_location_environmental_data(
            18.5204,
            73.8567,
            use_live_slope=True,
            db_path=test_db,
            staleness_hours=24,
        )
        assert mock_get.call_count == 1

    # Age cached record to 30 hours ago
    stale_dt = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
    conn = sqlite3.connect(test_db)
    conn.execute("UPDATE environmental_features SET retrieved_at = ? WHERE factor = 'slope'", (stale_dt,))
    conn.commit()
    conn.close()

    # Next call with 24-hr staleness should re-fetch with new response
    new_elevations = [100.0, 110.0, 100.0, 100.0, 100.0]  # dz/dy = 10/200 = 0.05 -> 5.0%
    with patch("requests.get", return_value=_mock_elevation_response(new_elevations)) as mock_get_refreshed:
        res = fetch_location_environmental_data(
            18.5204,
            73.8567,
            use_live_slope=True,
            db_path=test_db,
            staleness_hours=24,
        )
        assert mock_get_refreshed.call_count == 1
        assert res["values"]["slope"] == 5.0


def test_timeout_fallback_to_csv_with_warning(test_db):
    """When API times out, falls back to CSV slope value and appends warning."""
    with patch("requests.get", side_effect=requests.exceptions.Timeout("Connection timed out")):
        res = fetch_location_environmental_data(
            18.5204,
            73.8567,
            use_live_slope=True,
            db_path=test_db,
        )
        # Pune city slope from CSV is 3.0
        assert res["values"]["slope"] == 3.0
        assert res["metadata"]["slope"]["source"] == DEMO_SOURCE
        assert any("Live slope data from Open-Meteo was unavailable" in w for w in res["warnings"])
        assert res["live_slope_used"] is False


def test_http_error_fallback_no_invented_value(test_db):
    """When API fails and point is outside CSV coverage, value remains None (never invented)."""
    with patch("requests.get", side_effect=requests.exceptions.HTTPError("500 Server Error")):
        # Point far from Western Maharashtra sample data
        res = fetch_location_environmental_data(
            0.0,
            0.0,
            use_live_slope=True,
            db_path=test_db,
        )
        assert res["values"]["slope"] is None
        assert res["metadata"]["slope"]["source"] is None
        assert any("Live slope data from Open-Meteo was unavailable" in w for w in res["warnings"])
        assert res["live_slope_used"] is False


def test_flask_api_location_data_with_live_slope(tmp_path):
    """Integration test: GET /api/location-data with USE_LIVE_SLOPE=True in app config."""
    test_db_path = str(tmp_path / "api_live_slope.db")
    app = create_app({
        "DATABASE_PATH": test_db_path,
        "USE_LIVE_SLOPE": True,
        "TESTING": True,
    })

    with patch("requests.get", return_value=_mock_elevation_response()):
        with app.test_client() as client:
            res = client.get("/api/location-data?lat=18.5204&lon=73.8567")
            assert res.status_code == 200
            data = res.get_json()

            slope_factor = data["factors"]["slope"]
            assert slope_factor["value"] == 3.6
            assert slope_factor["source"] == OPEN_METEO_ELEVATION_SOURCE
            assert "90m" in slope_factor["resolution"]
            assert data["live_slope_used"] is True

            # Other factors remain demo values
            rainfall_factor = data["factors"]["annual_rainfall"]
            assert rainfall_factor["value"] == 740.0
            assert rainfall_factor["source"] == DEMO_SOURCE


def test_flask_api_assessments_with_live_slope(tmp_path):
    """Integration test: POST /api/assessments with USE_LIVE_SLOPE=True in app config."""
    test_db_path = str(tmp_path / "api_assess_slope.db")
    app = create_app({
        "DATABASE_PATH": test_db_path,
        "USE_LIVE_SLOPE": True,
        "TESTING": True,
    })

    with patch("requests.get", return_value=_mock_elevation_response()):
        with app.test_client() as client:
            payload = {
                "adaptation_id": "rain_garden",
                "reference_location": {"name": "Pune city", "latitude": 18.5204, "longitude": 73.8567},
                "target_location": {"name": "Pimpri", "latitude": 18.6298, "longitude": 73.7997},
            }
            res = client.post("/api/assessments", json=payload)
            assert res.status_code == 201
            data = res.get_json()

            factors = {f["factor"]: f for f in data["factors"]}
            assert factors["slope"]["source"] == OPEN_METEO_ELEVATION_SOURCE
            assert "90m" in factors["slope"]["resolution"]
            assert factors["annual_rainfall"]["source"] == DEMO_SOURCE
            assert factors["soil_infiltration"]["source"] == DEMO_SOURCE
            assert data["live_slope_used"] is True


def test_slope_header_badge_data_dependence(tmp_path):
    """
    Verify header badge and live_slope_used flag depend on the data:
    - If flag is off: live_slope_used is False.
    - If flag is on and live slope used: live_slope_used is True.
    - If flag is on but API fails (timeout/error): live_slope_used is False.
    """
    test_db_path = str(tmp_path / "badge_slope_test.db")

    # 1. Flag off -> live_slope_used is False
    app_off = create_app({"DATABASE_PATH": test_db_path, "USE_LIVE_SLOPE": False, "TESTING": True})
    with app_off.test_client() as client:
        res = client.get("/api/location-data?lat=18.5204&lon=73.8567")
        assert res.status_code == 200
        assert res.get_json()["live_slope_used"] is False

    # 2. Flag on + live success -> live_slope_used is True
    app_on = create_app({"DATABASE_PATH": test_db_path, "USE_LIVE_SLOPE": True, "TESTING": True})
    with patch("requests.get", return_value=_mock_elevation_response()):
        with app_on.test_client() as client:
            res = client.get("/api/location-data?lat=18.5204&lon=73.8567")
            assert res.status_code == 200
            assert res.get_json()["live_slope_used"] is True

    # 3. Flag on + API failure -> live_slope_used is False (falls back to demo data)
    with patch("requests.get", side_effect=requests.exceptions.Timeout("Timed out")):
        with app_on.test_client() as client:
            res = client.get("/api/location-data?lat=19.9975&lon=73.7898")
            assert res.status_code == 200
            assert res.get_json()["live_slope_used"] is False
