"""
Tests for parallel live data fetching, deadline enforcement, progressive streaming,
cache pre-warming, and honest data labeling.
"""

import json
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from app import create_app
from backend.data_fetcher import (
    DEMO_SOURCE,
    FACTOR_KEYS,
    NASA_POWER_SOURCE,
    OPEN_METEO_ELEVATION_SOURCE,
    OSM_SOURCE,
    SOILGRIDS_SOURCE,
    fetch_location_environmental_data,
    fetch_location_pair_environmental_data,
    start_cache_warming_if_needed,
)
from database.seed import seed


@pytest.fixture
def test_db(tmp_path):
    db_file = str(tmp_path / "test_live_parallel.db")
    seed(db_file)
    return db_file


def _mock_nasa_response(ann_val: float = 2.5):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
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
    resp.raise_for_status = MagicMock()
    return resp


def _mock_elevation_response():
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "elevation": [560.0, 562.0, 558.0, 561.0, 559.0]
    }
    resp.raise_for_status = MagicMock()
    return resp


def _mock_soilgrids_response():
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "properties": {
            "layers": [
                {
                    "name": "sand",
                    "depths": [{"label": "5-15cm", "values": {"mean": 450}}],
                },
                {
                    "name": "silt",
                    "depths": [{"label": "5-15cm", "values": {"mean": 350}}],
                },
                {
                    "name": "clay",
                    "depths": [{"label": "5-15cm", "values": {"mean": 200}}],
                },
            ]
        }
    }
    resp.raise_for_status = MagicMock()
    return resp


def _mock_overpass_open_space():
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "elements": [
            {
                "type": "count",
                "id": 0,
                "tags": {"total": "3", "ways": "3", "relations": "0"},
            }
        ]
    }
    resp.raise_for_status = MagicMock()
    return resp


def _mock_overpass_buildings():
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "elements": [
            {
                "type": "way",
                "id": 999,
                "bounds": {
                    "minlat": 18.5200,
                    "maxlat": 18.5202,
                    "minlon": 73.8565,
                    "maxlon": 73.8567,
                },
            }
        ]
    }
    resp.raise_for_status = MagicMock()
    return resp


def _mock_get_router(url, *args, **kwargs):
    if "power.larc.nasa.gov" in url:
        return _mock_nasa_response()
    elif "open-meteo.com" in url:
        return _mock_elevation_response()
    elif "rest.isric.org" in url:
        return _mock_soilgrids_response()
    resp = MagicMock()
    resp.status_code = 404
    resp.raise_for_status.side_effect = Exception("Not found")
    return resp


def _mock_post_router(url, *args, **kwargs):
    data = kwargs.get("data", "")
    if "leisure" in str(data):
        return _mock_overpass_open_space()
    return _mock_overpass_buildings()


# --------------------------------------------------------------------------- #
# 1. Parallel Source Fetching                                                 #
# --------------------------------------------------------------------------- #

def test_parallel_live_sources_fetch_all(test_db):
    """
    Fetch all live sources (NASA POWER, Open-Meteo, SoilGrids, Overpass) in parallel.
    Ensure all factors are populated with honest source labels and no invented data.
    """
    with patch("requests.get", side_effect=_mock_get_router), \
         patch("requests.post", side_effect=_mock_post_router):
        res = fetch_location_environmental_data(
            18.5204,
            73.8567,
            name="Pune city",
            use_live_rainfall=True,
            use_live_slope=True,
            use_live_soil=True,
            use_live_osm=True,
            db_path=test_db,
            timeout=5.0,
            deadline_seconds=12.0,
        )

        assert res["values"]["annual_rainfall"] is not None
        assert res["metadata"]["annual_rainfall"]["source"] == NASA_POWER_SOURCE
        assert res["live_rainfall_used"] is True

        assert res["values"]["slope"] is not None
        assert res["metadata"]["slope"]["source"] == OPEN_METEO_ELEVATION_SOURCE
        assert res["live_slope_used"] is True

        assert res["values"]["soil_infiltration"] is not None
        assert SOILGRIDS_SOURCE in res["metadata"]["soil_infiltration"]["source"]
        assert res["live_soil_used"] is True

        assert res["values"]["open_space"] == 1.0
        assert res["metadata"]["open_space"]["source"] == OSM_SOURCE

        assert res["values"]["building_distance"] is not None
        assert res["metadata"]["building_distance"]["source"] == OSM_SOURCE
        assert res["live_osm_used"] is True


# --------------------------------------------------------------------------- #
# 2. Parallel Location A and B Fetching with Deadline                         #
# --------------------------------------------------------------------------- #

def test_fetch_location_pair_parallel(test_db):
    """
    Fetch Location A and Location B in parallel using thread pool with deadline.
    """
    with patch("requests.get", side_effect=_mock_get_router), \
         patch("requests.post", side_effect=_mock_post_router):
        factor_events = []

        def on_factor(loc_key, f_key, payload):
            factor_events.append((loc_key, f_key, payload))

        loc_a = {"lat": 18.5204, "lon": 73.8567, "name": "Pune city"}
        loc_b = {"lat": 18.6298, "lon": 73.7997, "name": "Pimpri"}

        data_a, data_b = fetch_location_pair_environmental_data(
            loc_a,
            loc_b,
            use_live_rainfall=True,
            use_live_slope=True,
            use_live_soil=True,
            use_live_osm=True,
            db_path=test_db,
            timeout=5.0,
            deadline_seconds=12.0,
            on_factor_ready=on_factor,
        )

        assert data_a["values"]["annual_rainfall"] is not None
        assert data_b["values"]["annual_rainfall"] is not None
        assert len(factor_events) > 0

        # Verify factors arrive for both locations
        loc_keys_arrived = {evt[0] for evt in factor_events}
        assert "a" in loc_keys_arrived
        assert "b" in loc_keys_arrived


# --------------------------------------------------------------------------- #
# 3. Timeout and Deadline Fallback to Snapshot or Demo with Warning           #
# --------------------------------------------------------------------------- #

def test_deadline_miss_falls_back_with_data_quality_warning(test_db):
    """
    When live calls miss the deadline or raise timeout, fallback to cached snapshot or demo
    and attach a clear data_quality_warning.
    """
    release_event = threading.Event()

    def _slow_get(url, *args, **kwargs):
        # Wait until test asserts deadline fallback, then unblock cleanly
        release_event.wait(timeout=2.0)
        return _mock_nasa_response()

    try:
        with patch("requests.get", side_effect=_slow_get):
            res = fetch_location_environmental_data(
                18.5204,
                73.8567,
                name="Pune city",
                use_live_rainfall=True,
                use_live_slope=False,
                use_live_soil=False,
                use_live_osm=False,
                db_path=test_db,
                timeout=5.0,
                deadline_seconds=0.1,  # Short deadline to trigger deadline miss
            )

            # Fallback values must not be invented; should be demo or cached snapshot
            rain_meta = res["metadata"]["annual_rainfall"]
            assert rain_meta["source"] in (DEMO_SOURCE, "Live (cached snapshot, 2026-10-22)")
            assert any("deadline" in w or "timed out" in w or "timeout" in w.lower() for w in res["warnings"])
            assert res["live_rainfall_used"] is False
    finally:
        release_event.set()
        time.sleep(0.05)


# --------------------------------------------------------------------------- #
# 4. Progressive SSE Streaming (/api/preview-stream)                          #
# --------------------------------------------------------------------------- #

def test_progressive_preview_stream_sse(test_db):
    """
    The /api/preview-stream endpoint emits init, progressive factor events, and done event.
    """
    app = create_app({
        "DATABASE_PATH": test_db,
        "USE_LIVE_RAINFALL": True,
        "USE_LIVE_SLOPE": True,
        "TESTING": True,
    })

    with patch("requests.get", side_effect=_mock_get_router), \
         patch("requests.post", side_effect=_mock_post_router):
        with app.test_client() as client:
            resp = client.get(
                "/api/preview-stream?a_lat=18.5204&a_lon=73.8567&a_name=Pune&b_lat=18.6298&b_lon=73.7997&b_name=Pimpri"
            )
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers.get("Content-Type", "")

            body = resp.get_data(as_text=True)
            assert "event: init" in body
            assert "event: factor" in body
            assert "event: done" in body


# --------------------------------------------------------------------------- #
# 5. Background Thread Cache Pre-Warming at Startup                           #
# --------------------------------------------------------------------------- #

def test_cache_prewarming_background_thread_and_run_once(test_db):
    """
    Pre-warming runs off the main thread in a daemon thread, never blocks or crashes,
    and runs only once per boot.
    """
    with patch("backend.data_fetcher.fetch_location_environmental_data") as mock_fetch:
        mock_fetch.return_value = {"values": {}, "metadata": {}, "warnings": []}

        # Reset module-level prewarm flag for this test
        import backend.data_fetcher as df
        df._CACHE_WARM_STARTED = False

        started = start_cache_warming_if_needed(db_path=test_db)
        assert started is True

        # Calling again should return False (run once per boot)
        started2 = start_cache_warming_if_needed(db_path=test_db)
        assert started2 is False


# --------------------------------------------------------------------------- #
# 6. Honest Labels and UI Contract                                            #
# --------------------------------------------------------------------------- #

def test_honest_labels_contract(test_db):
    """Ensure labels are strictly honest: Live, Estimated, Snapshot, Demo, or None."""
    res = fetch_location_environmental_data(
        18.5204,
        73.8567,
        use_live_rainfall=False,
        use_live_slope=False,
        use_live_soil=False,
        use_live_osm=False,
        db_path=test_db,
    )
    for fk in FACTOR_KEYS:
        src = res["metadata"][fk]["source"]
        assert src == DEMO_SOURCE or src.startswith("Live") or src.startswith("Estimated")


def test_loading_banner_html_contains_required_message():
    """Verify frontend/templates/assessment.html contains the 30 seconds loading message."""
    with open("frontend/templates/assessment.html", "r", encoding="utf-8") as f:
        html = f.read()

    assert "Loading live data... this can take up to 30 seconds on first load" in html
    assert "loadingProgressBar" in html
    assert "liveDataLoadingBanner" in html
