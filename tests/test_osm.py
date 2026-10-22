"""
Tests for Live OpenStreetMap (Overpass API) open_space and building_distance
integration, caching, fallback, and configuration flag.
All HTTP calls are strictly mocked with no real network access.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
import pytest
import requests
import sqlite3

from app import create_app
from backend.data_fetcher import (
    OSM_SOURCE,
    OSM_RESOLUTION,
    DEMO_SOURCE,
    fetch_location_environmental_data,
    fetch_osm_open_space,
    fetch_osm_building_distance,
)
from database.seed import seed


@pytest.fixture
def test_db(tmp_path):
    """Create a temporary initialised SQLite database."""
    db_file = str(tmp_path / "test_osm.db")
    seed(db_path=db_file)
    return db_file


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

def _mock_overpass_open_space_response(total_count: int = 2):
    """Mock Overpass 'out count' response for open-space query."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "elements": [
            {
                "type": "count",
                "id": 0,
                "tags": {"total": str(total_count), "ways": str(total_count), "relations": "0"},
            }
        ]
    }
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


def _mock_overpass_no_open_space_response():
    """Mock Overpass 'out count' response with zero features."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "elements": [
            {
                "type": "count",
                "id": 0,
                "tags": {"total": "0", "ways": "0", "relations": "0"},
            }
        ]
    }
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


def _mock_overpass_buildings_response(buildings=None):
    """
    Mock Overpass 'out bb' response for building query.
    Default: two buildings, nearest centroid approx 15m from (18.5204, 73.8567).
    """
    if buildings is None:
        buildings = [
            {
                "type": "way",
                "id": 12345,
                "bounds": {
                    "minlat": 18.5203,
                    "maxlat": 18.5204,
                    "minlon": 73.8566,
                    "maxlon": 73.8568,
                },
            },
            {
                "type": "way",
                "id": 12346,
                "bounds": {
                    "minlat": 18.5210,
                    "maxlat": 18.5220,
                    "minlon": 73.8570,
                    "maxlon": 73.8580,
                },
            },
        ]
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"elements": buildings}
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


def _mock_overpass_no_buildings_response():
    """Mock Overpass response with no buildings."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"elements": []}
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


def _dual_osm_mock(open_space_resp, building_resp):
    """
    Return a side_effect list so that the first requests.post call gets the
    open_space response and the second gets the building response.
    """
    return [open_space_resp, building_resp]


# ---------------------------------------------------------------------------
# Flag behaviour tests
# ---------------------------------------------------------------------------

def test_flag_off_behaviour(test_db):
    """When USE_LIVE_OSM is false, no HTTP call; CSV values returned."""
    with patch("requests.post") as mock_post:
        res = fetch_location_environmental_data(
            18.5204,
            73.8567,
            use_live_osm=False,
            db_path=test_db,
        )
        mock_post.assert_not_called()
        assert res["values"]["open_space"] == 1.0
        assert res["values"]["building_distance"] == 6.0
        assert res["metadata"]["open_space"]["source"] == DEMO_SOURCE
        assert res["metadata"]["building_distance"]["source"] == DEMO_SOURCE
        assert res["live_osm_used"] is False


# ---------------------------------------------------------------------------
# open_space tests
# ---------------------------------------------------------------------------

def test_live_open_space_present(test_db):
    """When Overpass returns features, open_space = 1.0 and source is OSM."""
    open_mock = _mock_overpass_open_space_response(total_count=3)
    build_mock = _mock_overpass_buildings_response()
    with patch("requests.post", side_effect=_dual_osm_mock(open_mock, build_mock)) as mock_post:
        res = fetch_location_environmental_data(
            18.5204,
            73.8567,
            use_live_osm=True,
            db_path=test_db,
        )
        assert mock_post.called
        # Check first call went to Overpass
        args, kwargs = mock_post.call_args_list[0]
        assert kwargs.get("timeout") in (10.0, (5.0, 10.0))

        assert res["values"]["open_space"] == 1.0
        meta = res["metadata"]["open_space"]
        assert meta["source"] == OSM_SOURCE
        assert meta["source"].startswith("Live:")
        assert meta["resolution"] == OSM_RESOLUTION
        assert "present" in meta["transformation"]
        assert res["live_osm_used"] is True

        # Other factors unchanged
        assert res["values"]["annual_rainfall"] == 740.0
        assert res["metadata"]["annual_rainfall"]["source"] == DEMO_SOURCE


def test_live_open_space_absent(test_db):
    """When Overpass returns zero features, open_space = 0.0."""
    open_mock = _mock_overpass_no_open_space_response()
    build_mock = _mock_overpass_buildings_response()
    with patch("requests.post", side_effect=_dual_osm_mock(open_mock, build_mock)):
        res = fetch_location_environmental_data(
            18.5204,
            73.8567,
            use_live_osm=True,
            db_path=test_db,
        )
        assert res["values"]["open_space"] == 0.0
        assert res["metadata"]["open_space"]["source"] == OSM_SOURCE
        assert "absent" in res["metadata"]["open_space"]["transformation"]
        assert res["live_osm_used"] is True


# ---------------------------------------------------------------------------
# building_distance tests
# ---------------------------------------------------------------------------

def test_live_building_distance_with_buildings(test_db):
    """When buildings are found, returns haversine distance to nearest centroid."""
    open_mock = _mock_overpass_open_space_response(1)
    build_mock = _mock_overpass_buildings_response()
    with patch("requests.post", side_effect=_dual_osm_mock(open_mock, build_mock)):
        res = fetch_location_environmental_data(
            18.5204,
            73.8567,
            use_live_osm=True,
            db_path=test_db,
        )
        bd = res["values"]["building_distance"]
        assert bd is not None
        assert isinstance(bd, float)
        # Nearest building centroid is at ~(18.52035, 73.8567), should be a few metres
        assert 0.0 < bd < 500.0
        meta = res["metadata"]["building_distance"]
        assert meta["source"] == OSM_SOURCE
        assert meta["unit"] == "m"
        assert "haversine" in meta["transformation"]


def test_live_building_distance_no_buildings(test_db):
    """When no buildings found in radius, returns radius_m as conservative estimate."""
    open_mock = _mock_overpass_open_space_response(0)
    build_mock = _mock_overpass_no_buildings_response()
    with patch("requests.post", side_effect=_dual_osm_mock(open_mock, build_mock)):
        res = fetch_location_environmental_data(
            18.5204,
            73.8567,
            use_live_osm=True,
            db_path=test_db,
        )
        bd = res["values"]["building_distance"]
        assert bd == 200.0   # radius_m default
        assert res["metadata"]["building_distance"]["source"] == OSM_SOURCE


# ---------------------------------------------------------------------------
# Caching tests
# ---------------------------------------------------------------------------

def test_osm_open_space_cached_in_db(test_db):
    """open_space result is stored in environmental_features with all columns."""
    open_mock = _mock_overpass_open_space_response(2)
    build_mock = _mock_overpass_buildings_response()
    with patch("requests.post", side_effect=_dual_osm_mock(open_mock, build_mock)):
        fetch_location_environmental_data(
            18.5204,
            73.8567,
            use_live_osm=True,
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
        WHERE ef.factor = 'open_space'
        """
    )
    row = cur.fetchone()
    conn.close()

    assert row is not None
    assert row["value"] == 1.0
    assert row["unit"] == "binary (1=present, 0=absent)"
    assert row["source"] == OSM_SOURCE
    assert row["resolution"] is not None
    assert row["data_date"] is not None
    assert row["transformation"] is not None
    assert row["retrieved_at"] is not None


def test_osm_building_distance_cached_in_db(test_db):
    """building_distance result is stored in environmental_features with all columns."""
    open_mock = _mock_overpass_open_space_response(1)
    build_mock = _mock_overpass_buildings_response()
    with patch("requests.post", side_effect=_dual_osm_mock(open_mock, build_mock)):
        fetch_location_environmental_data(
            18.5204,
            73.8567,
            use_live_osm=True,
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
        WHERE ef.factor = 'building_distance'
        """
    )
    row = cur.fetchone()
    conn.close()

    assert row is not None
    assert row["value"] is not None
    assert row["unit"] == "m"
    assert row["source"] == OSM_SOURCE
    assert row["retrieved_at"] is not None
    assert "haversine" in row["transformation"]


def test_cache_reuse_within_staleness_hours(test_db):
    """Second call within staleness period uses cache; no second HTTP request."""
    open_mock = _mock_overpass_open_space_response(2)
    build_mock = _mock_overpass_buildings_response()
    with patch("requests.post", side_effect=_dual_osm_mock(open_mock, build_mock)) as mock_post:
        # First call → 2 HTTP requests (open_space + building_distance)
        res1 = fetch_location_environmental_data(
            18.5204,
            73.8567,
            use_live_osm=True,
            db_path=test_db,
            staleness_hours=24,
        )
        assert mock_post.call_count == 2
        assert res1["live_osm_used"] is True

        # Second call → cache hit, no additional HTTP requests
        res2 = fetch_location_environmental_data(
            18.5204,
            73.8567,
            use_live_osm=True,
            db_path=test_db,
            staleness_hours=24,
        )
        assert mock_post.call_count == 2   # unchanged
        assert res2["values"]["open_space"] == res1["values"]["open_space"]
        assert res2["metadata"]["open_space"]["source"] == OSM_SOURCE


def test_stale_cache_refreshes(test_db):
    """When cached entries are older than staleness_hours, both are re-fetched."""
    open_mock = _mock_overpass_open_space_response(1)
    build_mock = _mock_overpass_buildings_response()
    with patch("requests.post", side_effect=_dual_osm_mock(open_mock, build_mock)) as mock_post:
        fetch_location_environmental_data(
            18.5204,
            73.8567,
            use_live_osm=True,
            db_path=test_db,
            staleness_hours=24,
        )
        first_call_count = mock_post.call_count

    # Age the cached records to 30 hours ago
    stale_dt = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
    conn = sqlite3.connect(test_db)
    conn.execute(
        "UPDATE environmental_features SET retrieved_at = ? WHERE factor IN ('open_space', 'building_distance')",
        (stale_dt,),
    )
    conn.commit()
    conn.close()

    # Re-fetch with different responses
    open_mock2 = _mock_overpass_no_open_space_response()
    build_mock2 = _mock_overpass_no_buildings_response()
    with patch("requests.post", side_effect=_dual_osm_mock(open_mock2, build_mock2)) as mock_post2:
        res = fetch_location_environmental_data(
            18.5204,
            73.8567,
            use_live_osm=True,
            db_path=test_db,
            staleness_hours=24,
        )
        assert mock_post2.call_count == 2
        assert res["values"]["open_space"] == 0.0      # refreshed to absent
        assert res["values"]["building_distance"] == 200.0  # refreshed to no-buildings default


# ---------------------------------------------------------------------------
# Fallback tests
# ---------------------------------------------------------------------------

def test_timeout_fallback_open_space_with_warning(test_db):
    """On timeout for open_space Overpass call, uses cached snapshot if present, else falls back to CSV."""
    with patch("requests.post", side_effect=requests.exceptions.Timeout("timed out")):
        res = fetch_location_environmental_data(
            18.5204,
            73.8567,
            use_live_osm=True,
            db_path=test_db,
        )
        # Pune city has saved snapshot
        assert res["values"]["open_space"] == 1.0
        assert res["metadata"]["open_space"]["source"].startswith("Live (cached snapshot,")
        assert any("OpenStreetMap" in w for w in res["warnings"])
        assert res["live_osm_used"] is False

        # When no snapshot exists, falls back to CSV demo value
        res_no_snap = fetch_location_environmental_data(
            18.5204,
            73.8567,
            use_live_osm=True,
            db_path=test_db,
            snapshots_path="",
        )
        assert res_no_snap["values"]["open_space"] == 1.0
        assert res_no_snap["metadata"]["open_space"]["source"] == DEMO_SOURCE
        assert res_no_snap["live_osm_used"] is False


def test_http_error_fallback_no_invented_value(test_db):
    """On HTTP error outside CSV coverage, both OSM values stay None."""
    with patch("requests.post", side_effect=requests.exceptions.HTTPError("500")):
        res = fetch_location_environmental_data(
            0.0,
            0.0,
            use_live_osm=True,
            db_path=test_db,
            snapshots_path="",
        )
        assert res["values"]["open_space"] is None
        assert res["values"]["building_distance"] is None
        assert res["metadata"]["open_space"]["source"] is None
        assert any("OpenStreetMap" in w for w in res["warnings"])
        assert res["live_osm_used"] is False


def test_building_distance_error_but_open_space_ok(test_db):
    """
    When open_space succeeds but building_distance fails, live_osm_used is True
    (open_space succeeded), building_distance falls back to snapshot or CSV.
    """
    open_mock = _mock_overpass_open_space_response(2)

    def _osm_side_effect(*args, **kwargs):
        data = kwargs.get("data", {}).get("data", "")
        if "building" in data:
            raise requests.exceptions.Timeout("building timeout")
        return open_mock

    with patch("requests.post", side_effect=_osm_side_effect):
        # 1. With saved snapshot
        res = fetch_location_environmental_data(
            18.5204,
            73.8567,
            use_live_osm=True,
            db_path=test_db,
        )
        assert res["values"]["open_space"] == 1.0
        assert res["metadata"]["open_space"]["source"] == OSM_SOURCE
        assert res["values"]["building_distance"] == 15.0
        assert res["metadata"]["building_distance"]["source"].startswith("Live (cached snapshot,")

        # 2. Without snapshot -> falls back to CSV demo value
        res_no_snap = fetch_location_environmental_data(
            18.5204,
            73.8567,
            use_live_osm=True,
            db_path=test_db,
            snapshots_path="",
        )
        assert res_no_snap["values"]["open_space"] == 1.0
        assert res_no_snap["metadata"]["open_space"]["source"] == OSM_SOURCE
        assert res_no_snap["values"]["building_distance"] == 6.0
        assert res_no_snap["metadata"]["building_distance"]["source"] == DEMO_SOURCE
        assert any("OpenStreetMap" in w for w in res_no_snap["warnings"])


# ---------------------------------------------------------------------------
# Flask API integration tests
# ---------------------------------------------------------------------------

def test_flask_api_location_data_with_live_osm(tmp_path):
    """Integration: GET /api/location-data with USE_LIVE_OSM=True in app config."""
    test_db_path = str(tmp_path / "api_live_osm.db")
    app = create_app({
        "DATABASE_PATH": test_db_path,
        "USE_LIVE_OSM": True,
        "TESTING": True,
    })

    open_mock = _mock_overpass_open_space_response(3)
    build_mock = _mock_overpass_buildings_response()
    with patch("requests.post", side_effect=_dual_osm_mock(open_mock, build_mock)):
        with app.test_client() as client:
            res = client.get("/api/location-data?lat=18.5204&lon=73.8567")
            assert res.status_code == 200
            data = res.get_json()

            os_factor = data["factors"]["open_space"]
            assert os_factor["value"] == 1.0
            assert os_factor["source"].startswith("Live:")
            assert data["live_osm_used"] is True

            bd_factor = data["factors"]["building_distance"]
            assert bd_factor["source"].startswith("Live:")

            # Other factors remain demo
            rain_factor = data["factors"]["annual_rainfall"]
            assert rain_factor["source"] == DEMO_SOURCE


def test_flask_api_assessments_with_live_osm(tmp_path):
    """Integration: POST /api/assessments with USE_LIVE_OSM=True in app config."""
    test_db_path = str(tmp_path / "api_assess_osm.db")
    app = create_app({
        "DATABASE_PATH": test_db_path,
        "USE_LIVE_OSM": True,
        "TESTING": True,
    })

    open_mock = _mock_overpass_open_space_response(1)
    build_mock = _mock_overpass_buildings_response()
    # 4 calls: 2 for ref location, 2 for target location
    with patch(
        "requests.post",
        side_effect=_dual_osm_mock(open_mock, build_mock)
        + _dual_osm_mock(
            _mock_overpass_open_space_response(1),
            _mock_overpass_buildings_response(),
        ),
    ):
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
            os_src = (
                factors["open_space"].get("source")
                or factors["open_space"].get("b_source")
                or ""
            )
            assert "Live" in os_src or "OpenStreetMap" in os_src
            assert factors["annual_rainfall"]["source"] == DEMO_SOURCE
            assert data["live_osm_used"] is True


def test_osm_header_badge_data_dependence(tmp_path):
    """
    Verify live_osm_used flag:
    - Flag off → False
    - Flag on + live success → True
    - Flag on + API fails → False
    """
    test_db_path = str(tmp_path / "badge_osm_test.db")

    # 1. Flag off → False
    app_off = create_app({"DATABASE_PATH": test_db_path, "USE_LIVE_OSM": False, "TESTING": True})
    with app_off.test_client() as client:
        res = client.get("/api/location-data?lat=18.5204&lon=73.8567")
        assert res.status_code == 200
        assert res.get_json()["live_osm_used"] is False

    # 2. Flag on + live success → True
    app_on = create_app({"DATABASE_PATH": test_db_path, "USE_LIVE_OSM": True, "TESTING": True})
    open_mock = _mock_overpass_open_space_response(2)
    build_mock = _mock_overpass_buildings_response()
    with patch("requests.post", side_effect=_dual_osm_mock(open_mock, build_mock)):
        with app_on.test_client() as client:
            res = client.get("/api/location-data?lat=18.5204&lon=73.8567")
            assert res.status_code == 200
            assert res.get_json()["live_osm_used"] is True

    # 3. Flag on + API failure → False
    with patch("requests.post", side_effect=requests.exceptions.Timeout("Timed out")):
        with app_on.test_client() as client:
            res = client.get("/api/location-data?lat=19.9975&lon=73.7898")
            assert res.status_code == 200
            assert res.get_json()["live_osm_used"] is False
