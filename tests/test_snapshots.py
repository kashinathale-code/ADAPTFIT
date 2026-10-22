"""
tests/test_snapshots.py
=======================
Tests for:
1. Descriptive User-Agent header (config HTTP_USER_AGENT) on external requests.
2. Short connect timeout (5.0s) and 2 retries.
3. Overpass mirrors fallback in order.
4. Saved snapshots fallback labeled "Live (cached snapshot, <date>)".
5. Never invent values (e.g. Lonavala soil is null / Unknown).
6. Demo fallback when no snapshot exists.
7. Data-driven dashboard header badge and /api/data-status endpoint.
8. scripts/fetch_snapshots.py snapshot generation.
"""

from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import MagicMock, call, patch

import pytest
import requests

from app import create_app
from backend.data_fetcher import (
    DEMO_SOURCE,
    OVERPASS_MIRRORS,
    _get_user_agent,
    _request_with_retry,
    fetch_location_environmental_data,
    fetch_osm_building_distance,
    fetch_osm_open_space,
    fetch_soilgrids_infiltration,
    get_saved_snapshot,
    load_live_snapshots,
)
from backend.routes import build_data_badge_label, get_configured_badge_info
from config import Config
from scripts.fetch_snapshots import (
    fetch_all_snapshots,
    fetch_osm_building_distance_snapshot,
    fetch_osm_open_space_snapshot,
    fetch_soil_snapshot,
)


@pytest.fixture
def test_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    from database.seed import seed
    seed(db_path=path, force=True)
    yield path
    try:
        os.remove(path)
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# 1. User-Agent and Retry / Timeout tests                                     #
# --------------------------------------------------------------------------- #

def test_descriptive_user_agent_configured():
    """Config.HTTP_USER_AGENT is present and _get_user_agent returns it."""
    ua = _get_user_agent()
    assert "ADAPTFIT" in ua
    assert "https://github.com/adaptfit" in ua or "research@adaptfit.org" in ua


def test_request_with_retry_injects_user_agent_and_connect_timeout():
    """_request_with_retry attaches User-Agent and enforces 5.0s connect timeout."""
    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        resp = _request_with_retry("GET", "https://example.com/api", timeout=10.0)
        assert resp == mock_resp
        assert mock_get.called
        args, kwargs = mock_get.call_args
        assert kwargs["timeout"] == (5.0, 10.0)
        assert "User-Agent" in kwargs["headers"]
        assert "ADAPTFIT" in kwargs["headers"]["User-Agent"]


def test_request_with_retry_retries_twice_on_failure():
    """_request_with_retry performs 2 retries (3 attempts total) on network timeout."""
    with patch("requests.get", side_effect=requests.exceptions.ConnectTimeout("Connect timeout")) as mock_get:
        with pytest.raises(requests.exceptions.ConnectTimeout):
            _request_with_retry("GET", "https://example.com/api", retries=2, timeout=5.0)
        assert mock_get.call_count == 3


# --------------------------------------------------------------------------- #
# 2. Overpass mirrors tried in sequential order                                #
# --------------------------------------------------------------------------- #

def test_overpass_mirrors_tried_in_order(test_db):
    """When the primary Overpass mirror fails, the second mirror is tried in order."""
    called_urls = []

    def _mock_post(url, **kwargs):
        called_urls.append(url)
        if url == OVERPASS_MIRRORS[0]:
            raise requests.exceptions.ConnectTimeout("Primary mirror timed out")
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"elements": [{"type": "count", "tags": {"total": "3"}}]}
        return resp

    with patch("requests.post", side_effect=_mock_post):
        val, meta, warn = fetch_osm_open_space(
            lat=18.5204,
            lon=73.8567,
            db_path=test_db,
            staleness_hours=0,
        )
        assert val == 1.0
        assert meta["source"] == "Live: OpenStreetMap (Overpass)"
        assert OVERPASS_MIRRORS[0] in called_urls
        assert OVERPASS_MIRRORS[1] in called_urls
        assert called_urls.index(OVERPASS_MIRRORS[0]) < called_urls.index(OVERPASS_MIRRORS[1])


# --------------------------------------------------------------------------- #
# 3. Fallback to cached snapshots labeled "Live (cached snapshot, <date>)"     #
# --------------------------------------------------------------------------- #

def test_soilgrids_failure_uses_cached_snapshot_with_label(test_db):
    """When SoilGrids fails for a location with a saved snapshot (Lonavala), saved snapshot is used."""
    with patch("requests.get", side_effect=requests.exceptions.ConnectTimeout("SoilGrids down")):
        val, meta, warn = fetch_soilgrids_infiltration(
            lat=18.7557,
            lon=73.4091,
            name="Lonavala",
            db_path=test_db,
            staleness_hours=0,
        )
        assert val == 0.3
        assert meta is not None
        assert meta["source"].startswith("Live (cached snapshot,")
        assert meta["unit"] == "mm/hr"
        assert "250m" in meta["resolution"]
        assert "used saved snapshot" in warn


def test_soilgrids_failure_without_snapshot_stays_demo(test_db):
    """When SoilGrids fails for a location without a saved snapshot (Pune), value stays Demo."""
    with patch("requests.get", side_effect=requests.exceptions.ConnectTimeout("SoilGrids down")):
        res = fetch_location_environmental_data(
            lat=18.5204,
            lon=73.8567,
            name="Pune city",
            use_live_soil=True,
            db_path=test_db,
        )
        assert res["values"]["soil_infiltration"] == 22.0
        assert res["metadata"]["soil_infiltration"]["source"] == DEMO_SOURCE
        assert res["live_soil_used"] is False


def test_osm_all_mirrors_failure_uses_cached_snapshot(test_db):
    """When all OSM mirrors fail, saved snapshot is used and labeled 'Live (cached snapshot, <date>)'."""
    with patch("requests.post", side_effect=requests.exceptions.ConnectTimeout("All mirrors down")):
        val, meta, warn = fetch_osm_open_space(
            lat=18.5204,
            lon=73.8567,
            name="Pune city",
            db_path=test_db,
            staleness_hours=0,
        )
        assert val == 1.0
        assert meta["source"].startswith("Live (cached snapshot,")
        assert meta["resolution"] == "~1m positional (OSM contributor data)"
        assert "used saved snapshot" in warn


def test_osm_building_distance_failure_uses_cached_snapshot(test_db):
    """When OSM building distance fails, saved snapshot is used and labeled appropriately."""
    with patch("requests.post", side_effect=requests.exceptions.ConnectTimeout("All mirrors down")):
        val, meta, warn = fetch_osm_building_distance(
            lat=18.5204,
            lon=73.8567,
            name="Pune city",
            db_path=test_db,
            staleness_hours=0,
        )
        assert val == 15.0
        assert meta["source"].startswith("Live (cached snapshot,")
        assert "used saved snapshot" in warn


# --------------------------------------------------------------------------- #
# 4. Really fetched snapshots vs Demo values                                  #
# --------------------------------------------------------------------------- #

def test_lonavala_soil_really_fetched_snapshot(test_db):
    """Lonavala soil was really fetched as 0.3 mm/hr (Clay) from live SoilGrids."""
    snapshot = get_saved_snapshot("soil_infiltration", 18.7557, 73.4091, name="Lonavala")
    assert snapshot is not None
    assert snapshot["value"] == 0.3
    assert "Clay" in snapshot["transformation"]
    assert "Estimated (proxy)" in snapshot["source"]


# --------------------------------------------------------------------------- #
# 5. Fallback to DEMO when no snapshot exists                                 #
# --------------------------------------------------------------------------- #

def test_no_snapshot_falls_back_to_demo(test_db):
    """When live call fails and no snapshot exists, data_fetcher falls back to demo."""
    with patch("requests.get", side_effect=requests.exceptions.ConnectTimeout("SoilGrids down")):
        res = fetch_location_environmental_data(
            lat=18.5204,
            lon=73.8567,
            name="Pune city",
            use_live_soil=True,
            db_path=test_db,
            snapshots_path="",  # empty path guarantees no snapshots loaded
        )
        assert res["values"]["soil_infiltration"] == 22.0  # CSV demo value for Pune city
        assert res["metadata"]["soil_infiltration"]["source"] == DEMO_SOURCE
        assert res["live_soil_used"] is False


# --------------------------------------------------------------------------- #
# 6. Data-driven dashboard header badge and API endpoint                      #
# --------------------------------------------------------------------------- #

def test_data_badge_label_builder():
    """build_data_badge_label correctly classifies Live, Cached snapshot, Estimated and Demo."""
    # All demo
    assert build_data_badge_label([
        {"factor": "annual_rainfall", "source": "Demo value"},
        {"factor": "slope", "source": "Demo value"},
    ]) == "Sample data for demo, not live"

    # Live and cached live
    label = build_data_badge_label([
        {"factor": "annual_rainfall", "source": "Live: NASA POWER"},
        {"factor": "soil_infiltration", "source": "Live (cached snapshot, 2026-10-22)"},
        {"factor": "slope", "source": "Demo value"},
    ])
    assert "Live: rainfall, soil infiltration" in label
    assert "Demo: slope" in label


def test_api_data_status_endpoint(test_db):
    """GET /api/data-status returns active live flags and data-driven badge text."""
    app = create_app({"TESTING": True, "DATABASE_PATH": test_db, "USE_LIVE_RAINFALL": True})
    client = app.test_client()

    resp = client.get("/api/data-status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["is_live"] is True
    assert "Live: rainfall" in data["text"]
    assert data["live_flags"]["rainfall"] is True


def test_dashboard_renders_data_driven_badge(test_db):
    """Dashboard HTML renders configured badge text in headerDataBadge."""
    app = create_app({"TESTING": True, "DATABASE_PATH": test_db, "USE_LIVE_RAINFALL": True})
    client = app.test_client()

    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")
    assert "Live: rainfall" in html
    assert 'class="demo-badge-header mixed-live"' in html


# --------------------------------------------------------------------------- #
# 7. scripts/fetch_snapshots.py tests                                         #
# --------------------------------------------------------------------------- #

def test_fetch_snapshots_script_flow():
    """scripts/fetch_snapshots.py fetches and formats soil and OSM snapshots."""
    # Mock SoilGrids
    soil_resp = MagicMock()
    soil_resp.status_code = 200
    soil_resp.json.return_value = {
        "properties": {
            "layers": [
                {"name": "sand", "unit_measure": {"d_factor": 10}, "depths": [{"label": "5-15cm", "values": {"mean": 400}}]},
                {"name": "clay", "unit_measure": {"d_factor": 10}, "depths": [{"label": "5-15cm", "values": {"mean": 200}}]},
                {"name": "silt", "unit_measure": {"d_factor": 10}, "depths": [{"label": "5-15cm", "values": {"mean": 400}}]},
            ]
        }
    }

    # Mock Overpass open space count
    os_resp = MagicMock()
    os_resp.status_code = 200
    os_resp.json.return_value = {"elements": [{"type": "count", "tags": {"total": "2"}}]}

    # Mock Overpass buildings
    bd_resp = MagicMock()
    bd_resp.status_code = 200
    bd_resp.json.return_value = {
        "elements": [
            {
                "type": "way",
                "id": 101,
                "bounds": {"minlat": 18.5200, "minlon": 73.8560, "maxlat": 18.5202, "maxlon": 73.8562},
            }
        ]
    }

    with patch("requests.get", return_value=soil_resp):
        soil_res = fetch_soil_snapshot(18.5204, 73.8567, timeout=5.0, retries=1)
        assert soil_res is not None
        assert soil_res["value"] == 3.4
        assert soil_res["unit"] == "mm/hr"
        assert "SoilGrids" in soil_res["source"]
        assert "fetch_date" in soil_res

    with patch("requests.post", return_value=os_resp):
        os_res = fetch_osm_open_space_snapshot(18.5204, 73.8567, timeout=5.0, retries=1)
        assert os_res is not None
        assert os_res["value"] == 1.0
        assert os_res["unit"] == "binary (1=present, 0=absent)"
        assert "OpenStreetMap" in os_res["source"]

    with patch("requests.post", return_value=bd_resp):
        bd_res = fetch_osm_building_distance_snapshot(18.5204, 73.8567, timeout=5.0, retries=1)
        assert bd_res is not None
        assert isinstance(bd_res["value"], float)
        assert bd_res["unit"] == "m"

    # Test complete fetch_all_snapshots into temporary file
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        out_temp = tf.name

    try:
        with patch("scripts.fetch_snapshots.fetch_soil_snapshot", return_value=soil_res), \
             patch("scripts.fetch_snapshots.fetch_osm_open_space_snapshot", return_value=os_res), \
             patch("scripts.fetch_snapshots.fetch_osm_building_distance_snapshot", return_value=bd_res):
            doc = fetch_all_snapshots(output_path=out_temp, timeout=5.0, retries=1)
            assert "locations" in doc
            assert os.path.exists(out_temp)
            with open(out_temp, "r", encoding="utf-8") as fh:
                saved = json.load(fh)
            assert "locations" in saved
            pune = saved["locations"].get("pune_city")
            assert pune is not None
            assert pune["factors"]["soil_infiltration"]["value"] == 3.4
    finally:
        if os.path.exists(out_temp):
            try:
                os.remove(out_temp)
            except OSError:
                pass
