"""
Tests for Live NASA POWER rainfall integration, caching, fallback, and configuration flag.
All HTTP calls are strictly mocked with no real network access.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
import pytest
import requests
import sqlite3

from app import create_app
from backend.data_fetcher import (
    NASA_POWER_RESOLUTION,
    NASA_POWER_SOURCE,
    DEMO_SOURCE,
    fetch_location_environmental_data,
    fetch_nasa_power_rainfall,
)
from database.seed import seed


@pytest.fixture
def test_db(tmp_path):
    """Create a temporary initialized SQLite database."""
    db_file = str(tmp_path / "test_nasa.db")
    seed(db_path=db_file)
    return db_file


def _mock_nasa_response(ann_val: float = 2.5):
    """Return a mock requests.Response with valid NASA POWER climatology JSON."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "properties": {
            "parameter": {
                "PRECTOTCORR": {
                    "JAN": 0.1,
                    "FEB": 0.2,
                    "ANN": ann_val,
                }
            }
        },
        "header": {
            "parameters": {
                "PRECTOTCORR": {
                    "units": "mm/day",
                    "longname": "Precipitation Corrected",
                }
            }
        },
    }
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


def test_flag_off_behaviour(test_db):
    """When USE_LIVE_RAINFALL is false, behaviour is exactly as default (CSV only, no HTTP call)."""
    with patch("requests.get") as mock_get:
        res = fetch_location_environmental_data(
            18.5204,
            73.8567,
            use_live_rainfall=False,
            db_path=test_db,
        )
        mock_get.assert_not_called()
        assert res["values"]["annual_rainfall"] == 740.0
        assert res["metadata"]["annual_rainfall"]["source"] == DEMO_SOURCE
        assert res["metadata"]["annual_rainfall"]["resolution"] == "n/a (demo)"
        assert res["values"]["slope"] == 3.0


def test_live_rainfall_success_and_unit_conversion(test_db):
    """
    When USE_LIVE_RAINFALL is true, calls NASA POWER PRECTOTCORR,
    converts mm/day to mm/year (* 365.25), and keeps other factors from CSV.
    """
    with patch("requests.get", return_value=_mock_nasa_response(2.5)) as mock_get:
        res = fetch_location_environmental_data(
            18.5204,
            73.8567,
            use_live_rainfall=True,
            db_path=test_db,
        )
        assert mock_get.called
        # Check call arguments
        args, kwargs = mock_get.call_args
        assert "power.larc.nasa.gov" in args[0]
        assert kwargs.get("timeout") in (10.0, (5.0, 10.0))
        assert kwargs.get("params", {}).get("parameters") == "PRECTOTCORR"

        # Converted: 2.5 mm/day * 365.25 = 913.1 mm/yr
        assert res["values"]["annual_rainfall"] == 913.1
        meta = res["metadata"]["annual_rainfall"]
        assert meta["source"] == NASA_POWER_SOURCE
        assert meta["unit"] == "mm/yr"
        assert meta["resolution"] == NASA_POWER_RESOLUTION
        assert "0.5°" in meta["resolution"]
        assert "50 km" in meta["resolution"]
        assert "Converted from mm/day to mm/year" in meta["transformation"]

        # Other factors remain strictly from CSV
        assert res["values"]["slope"] == 3.0
        assert res["values"]["soil_infiltration"] == 22.0
        assert res["values"]["open_space"] == 1.0
        assert res["values"]["building_distance"] == 6.0
        assert res["metadata"]["slope"]["source"] == DEMO_SOURCE
        assert res["metadata"]["soil_infiltration"]["source"] == DEMO_SOURCE


def test_live_rainfall_cached_in_db(test_db):
    """Verify result is cached in environmental_features table."""
    with patch("requests.get", return_value=_mock_nasa_response(2.0)):
        fetch_location_environmental_data(
            18.5204,
            73.8567,
            use_live_rainfall=True,
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
        WHERE ef.factor = 'annual_rainfall'
        """
    )
    row = cur.fetchone()
    conn.close()

    assert row is not None
    assert row["value"] == 730.5  # 2.0 * 365.25
    assert row["unit"] == "mm/yr"
    assert row["source"] == NASA_POWER_SOURCE
    assert "0.5°" in row["resolution"]
    assert row["retrieved_at"] is not None


def test_cache_reuse_within_staleness_hours(test_db):
    """Second call reuses cache without issuing a second HTTP request."""
    with patch("requests.get", return_value=_mock_nasa_response(2.5)) as mock_get:
        # First call -> fetches and caches
        res1 = fetch_location_environmental_data(
            18.5204,
            73.8567,
            use_live_rainfall=True,
            db_path=test_db,
            staleness_hours=24,
        )
        assert mock_get.call_count == 1
        assert res1["values"]["annual_rainfall"] == 913.1

        # Second call -> cache hit
        res2 = fetch_location_environmental_data(
            18.5204,
            73.8567,
            use_live_rainfall=True,
            db_path=test_db,
            staleness_hours=24,
        )
        assert mock_get.call_count == 1  # Not called again
        assert res2["values"]["annual_rainfall"] == 913.1
        assert res2["metadata"]["annual_rainfall"]["source"] == NASA_POWER_SOURCE


def test_stale_cache_refreshes(test_db):
    """When cached entry is older than CACHE_STALENESS_HOURS, refreshes via API."""
    with patch("requests.get", return_value=_mock_nasa_response(2.0)) as mock_get:
        fetch_location_environmental_data(
            18.5204,
            73.8567,
            use_live_rainfall=True,
            db_path=test_db,
            staleness_hours=24,
        )
        assert mock_get.call_count == 1

    # Artificially age the cached record to 30 hours ago
    stale_dt = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
    conn = sqlite3.connect(test_db)
    conn.execute("UPDATE environmental_features SET retrieved_at = ?", (stale_dt,))
    conn.commit()
    conn.close()

    # Next call with 24-hr staleness should re-fetch
    with patch("requests.get", return_value=_mock_nasa_response(3.0)) as mock_get_refreshed:
        res = fetch_location_environmental_data(
            18.5204,
            73.8567,
            use_live_rainfall=True,
            db_path=test_db,
            staleness_hours=24,
        )
        assert mock_get_refreshed.call_count == 1
        assert res["values"]["annual_rainfall"] == 1095.8  # 3.0 * 365.25


def test_timeout_fallback_to_csv_with_warning(test_db):
    """When API times out, falls back to CSV value and appends warning."""
    with patch("requests.get", side_effect=requests.exceptions.Timeout("Connection timed out")):
        res = fetch_location_environmental_data(
            18.5204,
            73.8567,
            use_live_rainfall=True,
            db_path=test_db,
        )
        # Pune city rainfall from CSV
        assert res["values"]["annual_rainfall"] == 740.0
        assert res["metadata"]["annual_rainfall"]["source"] == DEMO_SOURCE
        assert any("Live rainfall data from NASA POWER was unavailable" in w for w in res["warnings"])


def test_http_error_fallback_no_invented_value(test_db):
    """When API fails and point is outside CSV coverage, value remains None (never invented)."""
    with patch("requests.get", side_effect=requests.exceptions.HTTPError("500 Server Error")):
        # Point far from Western Maharashtra sample data
        res = fetch_location_environmental_data(
            0.0,
            0.0,
            use_live_rainfall=True,
            db_path=test_db,
        )
        assert res["values"]["annual_rainfall"] is None
        assert res["metadata"]["annual_rainfall"]["source"] is None
        assert any("Live rainfall data from NASA POWER was unavailable" in w for w in res["warnings"])


def test_flask_api_location_data_with_live_rainfall(tmp_path):
    """Integration test: GET /api/location-data with USE_LIVE_RAINFALL=True in app config."""
    test_db_path = str(tmp_path / "api_live.db")
    app = create_app({
        "DATABASE_PATH": test_db_path,
        "USE_LIVE_RAINFALL": True,
        "TESTING": True,
    })

    with patch("requests.get", return_value=_mock_nasa_response(2.5)):
        with app.test_client() as client:
            res = client.get("/api/location-data?lat=18.5204&lon=73.8567")
            assert res.status_code == 200
            data = res.get_json()

            rain_factor = data["factors"]["annual_rainfall"]
            assert rain_factor["value"] == 913.1
            assert rain_factor["source"] == NASA_POWER_SOURCE
            assert "0.5°" in rain_factor["resolution"]

            # Other factors remain demo values
            slope_factor = data["factors"]["slope"]
            assert slope_factor["value"] == 3.0
            assert slope_factor["source"] == DEMO_SOURCE


def test_flask_api_assessments_with_live_rainfall(tmp_path):
    """Integration test: POST /api/assessments with USE_LIVE_RAINFALL=True in app config."""
    test_db_path = str(tmp_path / "api_assess.db")
    app = create_app({
        "DATABASE_PATH": test_db_path,
        "USE_LIVE_RAINFALL": True,
        "TESTING": True,
    })

    with patch("requests.get", return_value=_mock_nasa_response(2.0)):
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
            assert factors["annual_rainfall"]["source"] == NASA_POWER_SOURCE
            assert "0.5°" in factors["annual_rainfall"]["resolution"]
            assert factors["slope"]["source"] == DEMO_SOURCE
            assert factors["soil_infiltration"]["source"] == DEMO_SOURCE
            assert data["live_rainfall_used"] is True


def test_header_badge_data_dependence(tmp_path):
    """
    Verify header badge and live_rainfall_used flag depend on the data:
    - If flag is off: live_rainfall_used is False.
    - If flag is on and live rainfall used: live_rainfall_used is True.
    - If flag is on but API fails (timeout/error): live_rainfall_used is False.
    """
    test_db_path = str(tmp_path / "badge_test.db")

    # 1. Flag off -> live_rainfall_used is False
    app_off = create_app({"DATABASE_PATH": test_db_path, "USE_LIVE_RAINFALL": False, "TESTING": True})
    with app_off.test_client() as client:
        res = client.get("/api/location-data?lat=18.5204&lon=73.8567")
        assert res.status_code == 200
        assert res.get_json()["live_rainfall_used"] is False

    # 2. Flag on + live success -> live_rainfall_used is True
    app_on = create_app({"DATABASE_PATH": test_db_path, "USE_LIVE_RAINFALL": True, "TESTING": True})
    with patch("requests.get", return_value=_mock_nasa_response(2.5)):
        with app_on.test_client() as client:
            res = client.get("/api/location-data?lat=18.5204&lon=73.8567")
            assert res.status_code == 200
            assert res.get_json()["live_rainfall_used"] is True

    # 3. Flag on + API failure -> live_rainfall_used is False (falls back to demo data)
    with patch("requests.get", side_effect=requests.exceptions.Timeout("Timed out")):
        with app_on.test_client() as client:
            res = client.get("/api/location-data?lat=19.9975&lon=73.7898")
            assert res.status_code == 200
            assert res.get_json()["live_rainfall_used"] is False

