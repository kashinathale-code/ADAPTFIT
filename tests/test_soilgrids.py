"""
Tests for Live SoilGrids soil texture → infiltration integration, caching,
fallback, and configuration flag.
All HTTP calls are strictly mocked with no real network access.

Source for lookup table:
    Rawls, W.J., Brakensiek, D.L. & Miller, N. (1983). "Green-Ampt
    infiltration parameters from soil data." Journal of Hydraulic Engineering,
    109(1), 62-70. https://doi.org/10.1061/(ASCE)0733-9429(1983)109:1(62)
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
import pytest
import requests
import sqlite3

from app import create_app
from backend.data_fetcher import (
    SOILGRIDS_SOURCE,
    SOILGRIDS_RESOLUTION,
    DEMO_SOURCE,
    RAWLS_1983_KS_TABLE,
    infiltration_from_texture,
    fetch_location_environmental_data,
    fetch_soilgrids_infiltration,
)
from database.seed import seed


@pytest.fixture
def test_db(tmp_path):
    """Create a temporary initialised SQLite database."""
    db_file = str(tmp_path / "test_soilgrids.db")
    seed(db_path=db_file)
    return db_file


def _mock_soilgrids_response(texture_class: str = "Loam"):
    """Return a mock requests.Response with valid SoilGrids v2.0 TEXCLSS JSON."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "type": "Point",
        "geometry": {"type": "Point", "coordinates": [73.8567, 18.5204]},
        "properties": {
            "layers": [
                {
                    "name": "TEXCLSS",
                    "unit_measure": {"d_factor": 1, "mapped_units": "–", "target_units": "–"},
                    "depths": [
                        {
                            "label": "0-30cm",
                            "range": {"bottom_depth": 30, "top_depth": 0, "unit_depth": "cm"},
                            "values": {
                                "mean": texture_class,
                                "uncertainty": None,
                            },
                        }
                    ],
                }
            ]
        },
    }
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


# ---------------------------------------------------------------------------
# Unit tests for the lookup table and helper
# ---------------------------------------------------------------------------

class TestRawlsLookupTable:
    """Verify the Rawls et al. 1983 lookup table values."""

    def test_sand_ks(self):
        assert infiltration_from_texture("Sand") == 117.8

    def test_loamy_sand_ks(self):
        assert infiltration_from_texture("loamy sand") == 29.9

    def test_sandy_loam_ks(self):
        assert infiltration_from_texture("Sandy Loam") == 10.9

    def test_loam_ks(self):
        assert infiltration_from_texture("Loam") == 3.4

    def test_silt_loam_ks(self):
        assert infiltration_from_texture("Silt loam") == 6.5

    def test_sandy_clay_loam_ks(self):
        assert infiltration_from_texture("Sandy clay loam") == 1.5

    def test_clay_loam_ks(self):
        assert infiltration_from_texture("Clay loam") == 1.0

    def test_silty_clay_loam_ks(self):
        assert infiltration_from_texture("silty clay loam") == 1.0

    def test_sandy_clay_ks(self):
        assert infiltration_from_texture("Sandy clay") == 0.6

    def test_silty_clay_ks(self):
        assert infiltration_from_texture("silty clay") == 0.5

    def test_clay_ks(self):
        assert infiltration_from_texture("clay") == 0.3

    def test_case_insensitive(self):
        assert infiltration_from_texture("CLAY") == 0.3
        assert infiltration_from_texture("SAND") == 117.8

    def test_unknown_texture_returns_none(self):
        assert infiltration_from_texture("Gravel") is None
        assert infiltration_from_texture("unknown") is None

    def test_table_has_11_primary_classes(self):
        # Verify primary 11 USDA classes are all present
        primary = [
            "sand", "loamy sand", "sandy loam", "loam", "silt loam",
            "sandy clay loam", "clay loam", "silty clay loam",
            "sandy clay", "silty clay", "clay",
        ]
        for cls in primary:
            assert cls in RAWLS_1983_KS_TABLE, f"Missing: {cls}"


# ---------------------------------------------------------------------------
# Integration tests — flag behaviour
# ---------------------------------------------------------------------------

def test_flag_off_behaviour(test_db):
    """When USE_LIVE_SOIL is false, no HTTP call is made; CSV value is used."""
    with patch("requests.get") as mock_get:
        res = fetch_location_environmental_data(
            18.5204,
            73.8567,
            use_live_soil=False,
            db_path=test_db,
        )
        mock_get.assert_not_called()
        # CSV value for Pune city
        assert res["values"]["soil_infiltration"] == 22.0
        assert res["metadata"]["soil_infiltration"]["source"] == DEMO_SOURCE
        assert res["live_soil_used"] is False


def test_live_soil_success_loam(test_db):
    """
    When USE_LIVE_SOIL is true and SoilGrids returns 'Loam', infiltration is
    estimated as 3.4 mm/hr (Rawls 1983) and source is 'Estimated (proxy)'.
    """
    with patch("requests.get", return_value=_mock_soilgrids_response("Loam")) as mock_get:
        res = fetch_location_environmental_data(
            18.5204,
            73.8567,
            use_live_soil=True,
            db_path=test_db,
        )
        assert mock_get.called
        args, kwargs = mock_get.call_args
        assert kwargs.get("timeout") in (10.0, (5.0, 10.0))
        assert kwargs.get("params", {}).get("property") == "TEXCLSS"

        assert res["values"]["soil_infiltration"] == 3.4
        meta = res["metadata"]["soil_infiltration"]
        assert meta["source"] == SOILGRIDS_SOURCE
        assert meta["unit"] == "mm/hr"
        assert meta["resolution"] == SOILGRIDS_RESOLUTION
        assert "250m" in meta["resolution"]
        assert "Rawls et al." in meta["transformation"]
        assert "Loam" in meta["transformation"]
        assert res["live_soil_used"] is True

        # Other factors unchanged from CSV
        assert res["values"]["annual_rainfall"] == 740.0
        assert res["values"]["slope"] == 3.0
        assert res["metadata"]["annual_rainfall"]["source"] == DEMO_SOURCE


def test_live_soil_success_clay(test_db):
    """Clay texture → 0.3 mm/hr (Rawls 1983)."""
    with patch("requests.get", return_value=_mock_soilgrids_response("Clay")):
        res = fetch_location_environmental_data(
            18.5204,
            73.8567,
            use_live_soil=True,
            db_path=test_db,
        )
        assert res["values"]["soil_infiltration"] == 0.3
        assert res["live_soil_used"] is True


def test_live_soil_success_sand(test_db):
    """Sand texture → 117.8 mm/hr (Rawls 1983)."""
    with patch("requests.get", return_value=_mock_soilgrids_response("Sand")):
        res = fetch_location_environmental_data(
            18.5204,
            73.8567,
            use_live_soil=True,
            db_path=test_db,
        )
        assert res["values"]["soil_infiltration"] == 117.8
        assert res["live_soil_used"] is True


def test_estimated_proxy_label(test_db):
    """Source label must be 'Estimated (proxy)' not 'Live'."""
    with patch("requests.get", return_value=_mock_soilgrids_response("Sandy loam")):
        res = fetch_location_environmental_data(
            18.5204,
            73.8567,
            use_live_soil=True,
            db_path=test_db,
        )
        source = res["metadata"]["soil_infiltration"]["source"]
        assert source.startswith("Estimated (proxy)"), f"Expected 'Estimated (proxy)' label, got: {source!r}"
        assert "SoilGrids" in source


def test_live_soil_cached_in_db(test_db):
    """Result is stored in environmental_features with all required columns."""
    with patch("requests.get", return_value=_mock_soilgrids_response("Clay loam")):
        fetch_location_environmental_data(
            18.5204,
            73.8567,
            use_live_soil=True,
            db_path=test_db,
        )

    conn = sqlite3.connect(test_db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        """
        SELECT ef.factor, ef.value, ef.unit, ef.source, ef.resolution,
               ef.data_date, ef.transformation, ef.retrieved_at
        FROM environmental_features ef
        JOIN locations l ON ef.location_id = l.id
        WHERE ef.factor = 'soil_infiltration'
        """
    )
    row = cur.fetchone()
    conn.close()

    assert row is not None
    assert row["value"] == 1.0          # Clay loam Ks
    assert row["unit"] == "mm/hr"
    assert row["source"] == SOILGRIDS_SOURCE
    assert "250m" in row["resolution"]
    assert row["data_date"] is not None
    assert row["transformation"] is not None
    assert "Rawls" in row["transformation"]
    assert row["retrieved_at"] is not None


def test_cache_reuse_within_staleness_hours(test_db):
    """Second call within staleness period reuses cache without HTTP call."""
    with patch("requests.get", return_value=_mock_soilgrids_response("Sandy loam")) as mock_get:
        # First call → fetches and caches
        res1 = fetch_location_environmental_data(
            18.5204,
            73.8567,
            use_live_soil=True,
            db_path=test_db,
            staleness_hours=24,
        )
        assert mock_get.call_count == 1
        assert res1["values"]["soil_infiltration"] == 10.9

        # Second call → cache hit
        res2 = fetch_location_environmental_data(
            18.5204,
            73.8567,
            use_live_soil=True,
            db_path=test_db,
            staleness_hours=24,
        )
        assert mock_get.call_count == 1   # not called again
        assert res2["values"]["soil_infiltration"] == 10.9
        assert res2["metadata"]["soil_infiltration"]["source"] == SOILGRIDS_SOURCE


def test_stale_cache_refreshes(test_db):
    """When cached entry is older than staleness_hours, re-fetches from API."""
    with patch("requests.get", return_value=_mock_soilgrids_response("Sandy loam")) as mock_get:
        fetch_location_environmental_data(
            18.5204,
            73.8567,
            use_live_soil=True,
            db_path=test_db,
            staleness_hours=24,
        )
        assert mock_get.call_count == 1

    # Age the cached record to 30 hours ago
    stale_dt = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
    conn = sqlite3.connect(test_db)
    conn.execute(
        "UPDATE environmental_features SET retrieved_at = ? WHERE factor = 'soil_infiltration'",
        (stale_dt,),
    )
    conn.commit()
    conn.close()

    # Re-fetch with Clay loam this time
    with patch("requests.get", return_value=_mock_soilgrids_response("Clay loam")) as mock_get2:
        res = fetch_location_environmental_data(
            18.5204,
            73.8567,
            use_live_soil=True,
            db_path=test_db,
            staleness_hours=24,
        )
        assert mock_get2.call_count == 1
        assert res["values"]["soil_infiltration"] == 1.0   # Clay loam


def test_timeout_fallback_to_csv_with_warning(test_db):
    """On timeout, uses cached snapshot if present, else falls back to CSV value."""
    with patch("requests.get", side_effect=requests.exceptions.Timeout("timed out")):
        res = fetch_location_environmental_data(
            18.5204,
            73.8567,
            use_live_soil=True,
            db_path=test_db,
        )
        # Pune city has saved snapshot
        assert res["values"]["soil_infiltration"] == 14.8
        assert res["metadata"]["soil_infiltration"]["source"].startswith("Live (cached snapshot,")
        assert any("SoilGrids" in w for w in res["warnings"])
        assert res["live_soil_used"] is False

        # When no snapshot exists, falls back to CSV demo value
        res_no_snap = fetch_location_environmental_data(
            18.5204,
            73.8567,
            use_live_soil=True,
            db_path=test_db,
            snapshots_path="",
        )
        assert res_no_snap["values"]["soil_infiltration"] == 22.0
        assert res_no_snap["metadata"]["soil_infiltration"]["source"] == DEMO_SOURCE
        assert res_no_snap["live_soil_used"] is False


def test_http_error_fallback_no_invented_value(test_db):
    """On HTTP error outside CSV coverage, value stays None (never invented)."""
    with patch("requests.get", side_effect=requests.exceptions.HTTPError("500")):
        res = fetch_location_environmental_data(
            0.0,
            0.0,
            use_live_soil=True,
            db_path=test_db,
            snapshots_path="",
        )
        assert res["values"]["soil_infiltration"] is None
        assert res["metadata"]["soil_infiltration"]["source"] is None
        assert any("SoilGrids" in w for w in res["warnings"])
        assert res["live_soil_used"] is False


def test_empty_texture_class_fallback(test_db):
    """When SoilGrids returns no texture class string, falls back to saved snapshot or CSV."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "properties": {"layers": [{"name": "TEXCLSS", "depths": [{"values": {"mean": None}}]}]}
    }
    mock_resp.raise_for_status = MagicMock()
    with patch("requests.get", return_value=mock_resp):
        res = fetch_location_environmental_data(
            18.5204,
            73.8567,
            use_live_soil=True,
            db_path=test_db,
        )
        assert res["values"]["soil_infiltration"] == 14.8
        assert res["metadata"]["soil_infiltration"]["source"].startswith("Live (cached snapshot,")
        assert any("SoilGrids" in w for w in res["warnings"])
        assert res["live_soil_used"] is False

        # When no snapshot exists, falls back to CSV
        res_no_snap = fetch_location_environmental_data(
            18.5204,
            73.8567,
            use_live_soil=True,
            db_path=test_db,
            snapshots_path="",
        )
        assert res_no_snap["values"]["soil_infiltration"] == 22.0
        assert res_no_snap["metadata"]["soil_infiltration"]["source"] == DEMO_SOURCE
        assert res_no_snap["live_soil_used"] is False


def test_flask_api_location_data_with_live_soil(tmp_path):
    """Integration: GET /api/location-data with USE_LIVE_SOIL=True in app config."""
    test_db_path = str(tmp_path / "api_live_soil.db")
    app = create_app({
        "DATABASE_PATH": test_db_path,
        "USE_LIVE_SOIL": True,
        "TESTING": True,
    })

    with patch("requests.get", return_value=_mock_soilgrids_response("Loam")):
        with app.test_client() as client:
            res = client.get("/api/location-data?lat=18.5204&lon=73.8567")
            assert res.status_code == 200
            data = res.get_json()

            soil_factor = data["factors"]["soil_infiltration"]
            assert soil_factor["value"] == 3.4
            assert "Estimated (proxy)" in soil_factor["source"]
            assert "250m" in soil_factor["resolution"]
            assert data["live_soil_used"] is True

            # Other factors remain demo
            rain_factor = data["factors"]["annual_rainfall"]
            assert rain_factor["source"] == DEMO_SOURCE


def test_flask_api_assessments_with_live_soil(tmp_path):
    """Integration: POST /api/assessments with USE_LIVE_SOIL=True in app config."""
    test_db_path = str(tmp_path / "api_assess_soil.db")
    app = create_app({
        "DATABASE_PATH": test_db_path,
        "USE_LIVE_SOIL": True,
        "TESTING": True,
    })

    with patch("requests.get", return_value=_mock_soilgrids_response("Sandy loam")):
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
            soil_src = factors["soil_infiltration"].get("source") or factors["soil_infiltration"].get("b_source") or ""
            assert "Estimated (proxy)" in soil_src or "SoilGrids" in soil_src
            assert factors["annual_rainfall"]["source"] == DEMO_SOURCE
            assert data["live_soil_used"] is True


def test_soil_header_badge_data_dependence(tmp_path):
    """
    Verify live_soil_used flag:
    - Flag off → False
    - Flag on + live success → True
    - Flag on + API fails → False
    """
    test_db_path = str(tmp_path / "badge_soil_test.db")

    # 1. Flag off → False
    app_off = create_app({"DATABASE_PATH": test_db_path, "USE_LIVE_SOIL": False, "TESTING": True})
    with app_off.test_client() as client:
        res = client.get("/api/location-data?lat=18.5204&lon=73.8567")
        assert res.status_code == 200
        assert res.get_json()["live_soil_used"] is False

    # 2. Flag on + live success → True
    app_on = create_app({"DATABASE_PATH": test_db_path, "USE_LIVE_SOIL": True, "TESTING": True})
    with patch("requests.get", return_value=_mock_soilgrids_response("Loam")):
        with app_on.test_client() as client:
            res = client.get("/api/location-data?lat=18.5204&lon=73.8567")
            assert res.status_code == 200
            assert res.get_json()["live_soil_used"] is True

    # 3. Flag on + API failure → False (falls back to demo)
    with patch("requests.get", side_effect=requests.exceptions.Timeout("Timed out")):
        with app_on.test_client() as client:
            res = client.get("/api/location-data?lat=19.9975&lon=73.7898")
            assert res.status_code == 200
            assert res.get_json()["live_soil_used"] is False
