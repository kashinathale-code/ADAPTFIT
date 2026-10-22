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
    classify_usda_texture,
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


def _mock_soilgrids_response(texture_class: str = "Loam", sand: float = None, clay: float = None, silt: float = None, d_factor: int = 10):
    """Return a mock requests.Response with valid SoilGrids v2.0 sand, clay, silt JSON."""
    defaults = {
        "sand": (900, 50, 50),
        "loamy sand": (800, 80, 120),
        "sandy loam": (650, 150, 200),
        "loam": (400, 200, 400),
        "silt loam": (200, 150, 650),
        "silt": (50, 100, 850),
        "sandy clay loam": (550, 300, 150),
        "clay loam": (300, 350, 350),
        "silty clay loam": (100, 350, 550),
        "sandy clay": (500, 400, 100),
        "silty clay": (100, 450, 450),
        "clay": (200, 600, 200),
    }
    key = texture_class.strip().lower()
    if sand is None or clay is None or silt is None:
        sand_raw, clay_raw, silt_raw = defaults.get(key, (400, 200, 400))
    else:
        sand_raw = int(sand * d_factor)
        clay_raw = int(clay * d_factor)
        silt_raw = int(silt * d_factor)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [73.8567, 18.5204]},
        "properties": {
            "layers": [
                {
                    "name": "sand",
                    "unit_measure": {"d_factor": d_factor, "mapped_units": "cg/kg", "target_units": "g/kg"},
                    "depths": [{"label": "5-15cm", "values": {"mean": sand_raw}}],
                },
                {
                    "name": "clay",
                    "unit_measure": {"d_factor": d_factor, "mapped_units": "cg/kg", "target_units": "g/kg"},
                    "depths": [{"label": "5-15cm", "values": {"mean": clay_raw}}],
                },
                {
                    "name": "silt",
                    "unit_measure": {"d_factor": d_factor, "mapped_units": "cg/kg", "target_units": "g/kg"},
                    "depths": [{"label": "5-15cm", "values": {"mean": silt_raw}}],
                },
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


class TestUSDATextureClassification:
    """Verify programmatic USDA texture classification from sand, silt, and clay percentages."""

    def test_sand_classification(self):
        assert classify_usda_texture(90.0, 5.0, 5.0) == "sand"

    def test_loamy_sand_classification(self):
        assert classify_usda_texture(82.0, 10.0, 8.0) == "loamy sand"

    def test_sandy_loam_classification(self):
        assert classify_usda_texture(65.0, 20.0, 15.0) == "sandy loam"

    def test_loam_classification(self):
        assert classify_usda_texture(40.0, 40.0, 20.0) == "loam"

    def test_silt_loam_classification(self):
        assert classify_usda_texture(20.0, 65.0, 15.0) == "silt loam"

    def test_silt_classification(self):
        assert classify_usda_texture(5.0, 85.0, 10.0) == "silt"

    def test_sandy_clay_loam_classification(self):
        assert classify_usda_texture(55.0, 15.0, 30.0) == "sandy clay loam"

    def test_clay_loam_classification(self):
        assert classify_usda_texture(30.0, 35.0, 35.0) == "clay loam"

    def test_silty_clay_loam_classification(self):
        assert classify_usda_texture(10.0, 55.0, 35.0) == "silty clay loam"

    def test_sandy_clay_classification(self):
        assert classify_usda_texture(50.0, 10.0, 40.0) == "sandy clay"

    def test_silty_clay_classification(self):
        assert classify_usda_texture(10.0, 45.0, 45.0) == "silty clay"

    def test_clay_classification(self):
        assert classify_usda_texture(20.0, 20.0, 60.0) == "clay"

    def test_lonavala_soil_fractions(self):
        # 32.6% sand, 26.4% silt, 41.0% clay -> clay
        assert classify_usda_texture(32.6, 26.4, 41.0) == "clay"

    def test_invalid_or_none_inputs(self):
        assert classify_usda_texture(None, 20.0, 20.0) is None
        assert classify_usda_texture(0.0, 0.0, 0.0) is None


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
        params = kwargs.get("params", [])
        if isinstance(params, list):
            props = [v for k, v in params if k == "property"]
            assert set(props) == {"sand", "clay", "silt"}
            depths = [v for k, v in params if k == "depth"]
            assert "5-15cm" in depths
        elif isinstance(params, dict):
            assert "sand" in params.get("property", [])

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
    """On timeout, uses cached snapshot if present (Lonavala), else falls back to CSV value (Pune)."""
    with patch("requests.get", side_effect=requests.exceptions.Timeout("timed out")):
        # Location with saved snapshot (Lonavala: 0.3 mm/hr)
        res_snap = fetch_location_environmental_data(
            18.7557,
            73.4091,
            name="Lonavala",
            use_live_soil=True,
            db_path=test_db,
        )
        assert res_snap["values"]["soil_infiltration"] == 0.3
        assert res_snap["metadata"]["soil_infiltration"]["source"].startswith("Live (cached snapshot,")
        assert any("SoilGrids" in w for w in res_snap["warnings"])
        assert res_snap["live_soil_used"] is False

        # Location without saved snapshot (Pune city: 22.0 mm/hr CSV demo)
        res_no_snap = fetch_location_environmental_data(
            18.5204,
            73.8567,
            name="Pune city",
            use_live_soil=True,
            db_path=test_db,
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
    """When SoilGrids returns no valid numeric means, falls back to saved snapshot (if present) or CSV demo."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "properties": {
            "layers": [
                {"name": "sand", "depths": [{"label": "5-15cm", "values": {"mean": None}}]},
                {"name": "clay", "depths": [{"label": "5-15cm", "values": {"mean": None}}]},
                {"name": "silt", "depths": [{"label": "5-15cm", "values": {"mean": None}}]},
            ]
        }
    }
    mock_resp.raise_for_status = MagicMock()
    with patch("requests.get", return_value=mock_resp):
        # 1. Location with saved snapshot (Lonavala)
        res_snap = fetch_location_environmental_data(
            18.7557,
            73.4091,
            name="Lonavala",
            use_live_soil=True,
            db_path=test_db,
        )
        assert res_snap["values"]["soil_infiltration"] == 0.3
        assert res_snap["metadata"]["soil_infiltration"]["source"].startswith("Live (cached snapshot,")
        assert any("SoilGrids" in w for w in res_snap["warnings"])
        assert res_snap["live_soil_used"] is False

        # 2. Location without saved snapshot (Pune city) falls back to CSV demo value
        res_no_snap = fetch_location_environmental_data(
            18.5204,
            73.8567,
            name="Pune city",
            use_live_soil=True,
            db_path=test_db,
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
