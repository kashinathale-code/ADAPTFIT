"""
API integration tests for ADAPTFIT Flask endpoints.
Tests TRD Section 7 specification.
"""

import json
import pytest

from app import create_app


@pytest.fixture()
def client(tmp_path):
    test_db = str(tmp_path / "test_api.db")
    app = create_app({"DATABASE_PATH": test_db, "TESTING": True})
    with app.test_client() as client:
        yield client


def test_get_adaptations(client):
    res = client.get("/api/adaptations")
    assert res.status_code == 200
    data = res.get_json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert any(a["id"] == "rain_garden" for a in data)
    rain_garden = next(a for a in data if a["id"] == "rain_garden")
    assert rain_garden["name"] == "Rain Garden"


def test_get_location_data_valid(client):
    res = client.get("/api/location-data?lat=18.5204&lon=73.8567")
    assert res.status_code == 200
    data = res.get_json()
    assert data["latitude"] == 18.5204
    assert data["longitude"] == 73.8567
    assert "factors" in data
    # Environmental values from sample dataset for Pune city
    for factor in ("annual_rainfall", "slope", "soil_infiltration"):
        assert factor in data["factors"]
        assert data["factors"][factor]["value"] is not None
        assert "unit" in data["factors"][factor]
    assert data["factors"]["annual_rainfall"]["value"] == 740.0


def test_get_location_data_missing_params(client):
    res = client.get("/api/location-data")
    assert res.status_code == 400
    data = res.get_json()
    assert "error" in data


def test_get_location_data_invalid_coordinates(client):
    res = client.get("/api/location-data?lat=195.0&lon=73.85")
    assert res.status_code == 400
    data = res.get_json()
    assert "error" in data


def test_post_assessment_unknown_adaptation_returns_404(client):
    payload = {
        "adaptation_id": "non_existent_adaptation",
        "reference_location": {"name": "Location A", "latitude": 19.10, "longitude": 73.00},
        "target_location": {"name": "Niphad, Nashik", "latitude": 20.08, "longitude": 74.11},
    }
    res = client.post("/api/assessments", json=payload)
    assert res.status_code == 404
    data = res.get_json()
    assert "error" in data


def test_post_assessment_invalid_coordinates_returns_400(client):
    payload = {
        "adaptation_id": "rain_garden",
        "reference_location": {"name": "Location A", "latitude": "invalid", "longitude": 73.00},
        "target_location": {"name": "Niphad, Nashik", "latitude": 20.08, "longitude": 74.11},
    }
    res = client.post("/api/assessments", json=payload)
    assert res.status_code == 400
    data = res.get_json()
    assert "error" in data


def test_post_assessment_valid_trd_response_format(client):
    # Assessment with Niphad target from sample CSV (evaluates factors and returns TRD §7 format)
    payload = {
        "adaptation_id": "rain_garden",
        "reference_location": {"name": "Location A", "latitude": 19.10, "longitude": 73.00},
        "target_location": {"name": "Niphad, Nashik", "latitude": 20.08, "longitude": 74.11},
    }
    res = client.post("/api/assessments", json=payload)
    assert res.status_code == 201
    data = res.get_json()

    # Verify TRD §7 fields
    assert "assessment_id" in data
    assert "status" in data
    assert "score" in data
    assert "factors" in data
    assert "supporting_factors" in data
    assert "limiting_factors" in data
    assert "suggested_checks" in data
    assert "data_quality_warnings" in data
    assert "disclaimer" in data

    # Verify factor structure
    assert len(data["factors"]) == 5
    first_factor = data["factors"][0]
    for key in ("factor", "a_value", "b_value", "requirement", "factor_status", "transfer_risk", "interpretation", "source", "resolution"):
        assert key in first_factor


def test_post_assessment_with_explicit_factors(client):
    # Assessment with provided factors matching TC-1 (all suitable)
    payload = {
        "adaptation_id": "rain_garden",
        "reference_location": {
            "name": "Location A",
            "latitude": 19.10,
            "longitude": 73.00,
            "factors": {
                "soil_infiltration": 30.0,
                "slope": 3.0,
                "annual_rainfall": 1200.0,
                "open_space": 1.0,
                "building_distance": 5.0,
            },
        },
        "target_location": {
            "name": "Niphad, Nashik",
            "latitude": 20.08,
            "longitude": 74.11,
            "factors": {
                "soil_infiltration": 28.0,
                "slope": 4.0,
                "annual_rainfall": 1100.0,
                "open_space": 1.0,
                "building_distance": 6.0,
            },
        },
    }
    res = client.post("/api/assessments", json=payload)
    assert res.status_code == 201
    data = res.get_json()
    assert data["status"] == "suitable"
    assert data["score"] is not None
    assert len(data["limiting_factors"]) == 0
    assert len(data["supporting_factors"]) == 5


def test_get_assessment_by_id(client):
    payload = {
        "adaptation_id": "rain_garden",
        "reference_location": {
            "name": "Location A",
            "latitude": 19.10,
            "longitude": 73.00,
            "factors": {"soil_infiltration": 30.0, "slope": 3.0, "annual_rainfall": 1200.0, "open_space": 1.0, "building_distance": 5.0},
        },
        "target_location": {
            "name": "Location B",
            "latitude": 20.08,
            "longitude": 74.11,
            "factors": {"soil_infiltration": 28.0, "slope": 4.0, "annual_rainfall": 1100.0, "open_space": 1.0, "building_distance": 6.0},
        },
    }
    post_res = client.post("/api/assessments", json=payload)
    assessment_id = post_res.get_json()["assessment_id"]

    get_res = client.get(f"/api/assessments/{assessment_id}")
    assert get_res.status_code == 200
    get_data = get_res.get_json()
    assert get_data["assessment_id"] == assessment_id
    assert get_data["status"] == "suitable"
    assert len(get_data["factors"]) == 5
    assert get_data["reference_location"]["name"] == "Location A"
    assert get_data["reference_location"]["latitude"] == 19.10
    assert get_data["reference_location"]["longitude"] == 73.00
    assert get_data["target_location"]["name"] == "Location B"
    assert get_data["target_location"]["latitude"] == 20.08
    assert get_data["target_location"]["longitude"] == 74.11


def test_get_assessment_custom_locations_from_db(client):
    """Verify GET /api/assessments/<id> returns name, lat, and lon read from locations table."""
    payload = {
        "adaptation_id": "rain_garden",
        "reference_location": {
            "name": "Pune city",
            "latitude": 18.5204,
            "longitude": 73.8567,
            "factors": {"soil_infiltration": 30.0, "slope": 3.0, "annual_rainfall": 1200.0, "open_space": 1.0, "building_distance": 5.0},
        },
        "target_location": {
            "name": "Niphad",
            "latitude": 20.0800,
            "longitude": 74.1100,
            "factors": {"soil_infiltration": 28.0, "slope": 4.0, "annual_rainfall": 1100.0, "open_space": 1.0, "building_distance": 6.0},
        },
    }
    post_res = client.post("/api/assessments", json=payload)
    assert post_res.status_code == 201
    aid = post_res.get_json()["assessment_id"]

    get_res = client.get(f"/api/assessments/{aid}")
    assert get_res.status_code == 200
    data = get_res.get_json()

    assert data["reference_location"]["name"] == "Pune city"
    assert data["reference_location"]["latitude"] == 18.5204
    assert data["reference_location"]["longitude"] == 73.8567

    assert data["target_location"]["name"] == "Niphad"
    assert data["target_location"]["latitude"] == 20.0800
    assert data["target_location"]["longitude"] == 74.1100


def test_get_assessment_not_found(client):
    res = client.get("/api/assessments/999999")
    assert res.status_code == 404
    assert "error" in res.get_json()


def test_frontend_dashboard_page(client):
    res = client.get("/")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "Could this adaptation work in a new place?" in html
    assert "ADAPTFIT" in html
    assert "Right adaptation. Right place." in html
    assert "Start new assessment" in html
    assert "preliminary, explainable decision-support prototype" in html


def test_frontend_new_assessment_page(client):
    res = client.get("/new")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "New Transferability Assessment" in html
    assert "leafletMap" in html
    assert "newAssessmentDataBadge" in html
    assert "previewTableHeaderBadge" in html
    assert "candidate, unverified" in html
    assert "applyDemoProfile('conditional')" in html
    assert "applyDemoProfile('insufficient_data')" in html
    assert "Run assessment" in html


def test_frontend_results_page(client):
    res = client.get("/results")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "Assessment Results" in html
    assert "not a probability" in html
    assert "based on known factors only" in html


def test_auto_seeding_on_startup_when_db_missing(tmp_path):
    """Verify database auto-seeding on startup when the database file is missing (TRD §5, §10)."""
    import os
    missing_db = str(tmp_path / "autoseed_dir" / "missing.db")
    assert not os.path.exists(missing_db)

    test_app = create_app({"DATABASE_PATH": missing_db, "TESTING": True})
    assert os.path.exists(missing_db)

    with test_app.test_client() as tc:
        res = tc.get("/api/adaptations")
        assert res.status_code == 200
        adaptations = res.get_json()
        assert any(a["id"] == "rain_garden" for a in adaptations)


def test_config_wiring_suitable_min_changes_status(tmp_path):
    """Verify that changing app.config['SUITABLE_MIN'] changes assessment status from suitable to conditional."""
    test_db = str(tmp_path / "test_cfg_suitable.db")
    payload = {
        "adaptation_id": "rain_garden",
        "reference_location": {
            "name": "Location A",
            "latitude": 19.10,
            "longitude": 73.00,
            "factors": {"soil_infiltration": 30.0, "slope": 3.0, "annual_rainfall": 1200.0, "open_space": 1.0, "building_distance": 5.0},
        },
        "target_location": {
            "name": "Location B",
            "latitude": 20.08,
            "longitude": 74.11,
            "factors": {"soil_infiltration": 28.0, "slope": 4.0, "annual_rainfall": 1100.0, "open_space": 1.0, "building_distance": 6.0},
        },
    }

    # Standard config: SUITABLE_MIN=0.75 -> status is "suitable"
    app_default = create_app({"DATABASE_PATH": test_db, "SUITABLE_MIN": 0.75, "TESTING": True})
    with app_default.test_client() as c:
        res = c.post("/api/assessments", json=payload)
        assert res.status_code == 201
        data = res.get_json()
        assert data["status"] == "suitable"
        assert data["suitable_min"] == 0.75

    # Strict config: SUITABLE_MIN=1.05 -> score (~1.0) < 1.05 -> status becomes "conditional"
    app_strict = create_app({"DATABASE_PATH": test_db, "SUITABLE_MIN": 1.05, "TESTING": True})
    with app_strict.test_client() as c:
        res = c.post("/api/assessments", json=payload)
        assert res.status_code == 201
        data = res.get_json()
        assert data["status"] == "conditional"
        assert data["suitable_min"] == 1.05


def test_config_wiring_max_missing_weight_changes_status(tmp_path):
    """Verify that lowering app.config['MAX_MISSING_WEIGHT'] changes assessment status to insufficient_data."""
    test_db = str(tmp_path / "test_cfg_missing.db")
    # building_distance has weight 0.10. If missing, unknown weight = 0.10
    payload = {
        "adaptation_id": "rain_garden",
        "reference_location": {
            "name": "Location A",
            "latitude": 19.10,
            "longitude": 73.00,
            "factors": {"soil_infiltration": 30.0, "slope": 3.0, "annual_rainfall": 1200.0, "open_space": 1.0, "building_distance": 5.0},
        },
        "target_location": {
            "name": "Location B",
            "latitude": 20.08,
            "longitude": 74.11,
            "factors": {"soil_infiltration": 28.0, "slope": 4.0, "annual_rainfall": 1100.0, "open_space": 1.0, "building_distance": None},
        },
    }

    # Default MAX_MISSING_WEIGHT=0.30: 0.10 <= 0.30 -> conditional
    app_default = create_app({"DATABASE_PATH": test_db, "MAX_MISSING_WEIGHT": 0.30, "TESTING": True})
    with app_default.test_client() as c:
        res = c.post("/api/assessments", json=payload)
        assert res.status_code == 201
        data = res.get_json()
        assert data["status"] == "conditional"
        assert data["max_missing_weight"] == 0.30

    # Strict MAX_MISSING_WEIGHT=0.05: 0.10 > 0.05 -> insufficient_data
    app_strict = create_app({"DATABASE_PATH": test_db, "MAX_MISSING_WEIGHT": 0.05, "TESTING": True})
    with app_strict.test_client() as c:
        res = c.post("/api/assessments", json=payload)
        assert res.status_code == 201
        data = res.get_json()
        assert data["status"] == "insufficient_data"
        assert data["max_missing_weight"] == 0.05


def test_assessment_evidence_and_rule_version(client):
    # 1. Check GET /api/adaptations
    res_adapt = client.get("/api/adaptations")
    assert res_adapt.status_code == 200
    adapt_data = res_adapt.get_json()
    assert isinstance(adapt_data, list)
    rg = next(a for a in adapt_data if a["id"] == "rain_garden")
    for req in rg["requirements"]:
        assert "evidence" in req
        assert "rule_version" in req
        assert req["evidence"] != ""
        assert req["rule_version"] != ""

    # Check that soil_infiltration has verified evidence citation
    soil_req = next(r for r in rg["requirements"] if r["factor"] == "soil_infiltration")
    assert "v1.0-verified" in soil_req["rule_version"]
    assert "EPA" in soil_req["evidence"]

    # Check that annual_rainfall is candidate, unverified
    rain_req = next(r for r in rg["requirements"] if r["factor"] == "annual_rainfall")
    assert "candidate" in rain_req["rule_version"]
    assert "candidate, unverified" in rain_req["evidence"]

    # 2. Check POST /api/assessments
    payload = {
        "adaptation_id": "rain_garden",
        "reference_location": {"name": "Location A", "latitude": 19.10, "longitude": 73.00},
        "target_location": {"name": "Niphad, Nashik", "latitude": 20.08, "longitude": 74.11},
    }
    res_post = client.post("/api/assessments", json=payload)
    assert res_post.status_code == 201
    post_data = res_post.get_json()
    for factor in post_data["factors"]:
        assert "evidence" in factor
        assert "rule_version" in factor
        assert factor["evidence"] != ""
        assert factor["rule_version"] != ""

    # 3. Check GET /api/assessments/<id>
    assessment_id = post_data["assessment_id"]
    res_get = client.get(f"/api/assessments/{assessment_id}")
    assert res_get.status_code == 200
    get_data = res_get.get_json()
    for factor in get_data["factors"]:
        assert "evidence" in factor
        assert "rule_version" in factor
        assert factor["evidence"] != ""
        assert factor["rule_version"] != ""


def test_list_assessments_endpoint(client):
    # Create 3 assessments
    for i in range(3):
        payload = {
            "adaptation_id": "rain_garden",
            "reference_location": {"name": f"City A-{i}", "latitude": 18.52, "longitude": 73.85},
            "target_location": {"name": f"City B-{i}", "latitude": 18.63, "longitude": 73.80},
        }
        res = client.post("/api/assessments", json=payload)
        assert res.status_code == 201

    # Call GET /api/assessments
    res_list = client.get("/api/assessments?page=1&limit=2")
    assert res_list.status_code == 200
    data = res_list.get_json()
    assert "assessments" in data
    assert "total" in data
    assert "pages" in data
    assert data["total"] >= 3
    assert len(data["assessments"]) == 2
    assert data["page"] == 1
    assert data["per_page"] == 2

    # Check newest first ordering
    first = data["assessments"][0]
    second = data["assessments"][1]
    assert first["id"] > second["id"]
    assert "status" in first
    assert "score" in first
    assert "location_a" in first
    assert "location_b" in first


def test_frontend_history_page(client):
    # Verify /history route
    res = client.get("/history")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "Assessment History" in html
    assert "historyTable" in html
    assert "PRD §13" in html

    # Verify dashboard button in index links to /history
    res_index = client.get("/")
    assert res_index.status_code == 200
    index_html = res_index.get_data(as_text=True)
    assert 'href="/history"' in index_html
    assert "View recent results" in index_html


def test_self_hosted_leaflet_assets(client):
    # Verify Leaflet CSS static vendor file
    res_css = client.get("/static/vendor/leaflet/leaflet.css")
    assert res_css.status_code == 200
    assert "leaflet" in res_css.get_data(as_text=True).lower()

    # Verify Leaflet JS static vendor file
    res_js = client.get("/static/vendor/leaflet/leaflet.js")
    assert res_js.status_code == 200

    # Verify marker icon image exists
    res_img = client.get("/static/vendor/leaflet/images/marker-icon.png")
    assert res_img.status_code == 200

    # Verify base.html references local vendor files rather than CDN
    res_base = client.get("/")
    html = res_base.get_data(as_text=True)
    assert "/static/vendor/leaflet/leaflet.css" in html
    assert "/static/vendor/leaflet/leaflet.js" in html
    assert "unpkg.com/leaflet" not in html


def test_geocode_endpoint_validation(client):
    # Missing query
    res = client.get("/api/geocode")
    assert res.status_code == 400
    assert "error" in res.get_json()

    # Empty query
    res_empty = client.get("/api/geocode?q=  ")
    assert res_empty.status_code == 400


def test_geocode_endpoint_mocked_http_and_caching(client, monkeypatch):
    import requests

    call_count = 0

    class MockResponse:
        status_code = 200
        def raise_for_status(self):
            pass
        def json(self):
            return [
                {
                    "lat": "18.5204",
                    "lon": "73.8567",
                    "display_name": "Pune, Maharashtra, India",
                    "name": "Pune",
                    "type": "city",
                    "importance": 0.88,
                }
            ]

    def mock_get(url, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        assert "nominatim.openstreetmap.org" in url
        # Verify custom User-Agent header per Nominatim policy
        headers = kwargs.get("headers", {})
        assert "User-Agent" in headers
        assert "ADAPTFIT" in headers["User-Agent"]
        return MockResponse()

    monkeypatch.setattr(requests, "get", mock_get)

    # First call: hits mocked Nominatim
    res1 = client.get("/api/geocode?q=Pune")
    assert res1.status_code == 200
    d1 = res1.get_json()
    assert d1["query"] == "Pune"
    assert len(d1["results"]) == 1
    assert d1["results"][0]["name"] == "Pune"
    assert d1["results"][0]["latitude"] == 18.5204
    assert d1["results"][0]["longitude"] == 73.8567
    assert call_count == 1

    # Second call: must be served from cache without calling requests.get again
    res2 = client.get("/api/geocode?q=Pune")
    assert res2.status_code == 200
    d2 = res2.get_json()
    assert len(d2["results"]) == 1
    assert d2["results"][0]["name"] == "Pune"
    assert call_count == 1, "Expected second call to use SQLite geocoding cache"


def test_geocode_endpoint_fallback_on_failure(client, monkeypatch):
    import requests

    def mock_get_fail(url, *args, **kwargs):
        raise requests.RequestException("Simulated connection timeout")

    monkeypatch.setattr(requests, "get", mock_get_fail)

    # Searching for a sample place like "Pimpri" should fall back to sample CSV without crashing
    res = client.get("/api/geocode?q=Pimpri")
    assert res.status_code == 200
    data = res.get_json()
    assert "results" in data
    assert any("Pimpri" in r["name"] for r in data["results"])


def test_geocode_ui_elements_in_assessment_page(client):
    res = client.get("/new")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "locA_search" in html
    assert "locB_search" in html
    assert "searchPlace('A')" in html
    assert "searchPlace('B')" in html


# --------------------------------------------------------------------------- #
# Multi-Target Comparison Tests (FR-11)                                       #
# --------------------------------------------------------------------------- #

def test_post_comparisons_validation(client):
    # Missing / empty payload
    r = client.post("/api/comparisons", json="not a dict")
    assert r.status_code == 400

    # Missing adaptation_id
    r = client.post(
        "/api/comparisons",
        json={
            "reference_location": {"latitude": 18.5204, "longitude": 73.8567},
            "targets": [{"latitude": 18.6298, "longitude": 73.7997}],
        },
    )
    assert r.status_code == 400
    assert "adaptation_id" in r.get_json()["error"]

    # Unknown adaptation_id
    r = client.post(
        "/api/comparisons",
        json={
            "adaptation_id": "non_existent_adaptation",
            "reference_location": {"latitude": 18.5204, "longitude": 73.8567},
            "targets": [{"latitude": 18.6298, "longitude": 73.7997}],
        },
    )
    assert r.status_code == 404

    # Missing reference_location
    r = client.post(
        "/api/comparisons",
        json={
            "adaptation_id": "rain_garden",
            "targets": [{"latitude": 18.6298, "longitude": 73.7997}],
        },
    )
    assert r.status_code == 400

    # Empty targets list
    r = client.post(
        "/api/comparisons",
        json={
            "adaptation_id": "rain_garden",
            "reference_location": {"latitude": 18.5204, "longitude": 73.8567},
            "targets": [],
        },
    )
    assert r.status_code == 400
    assert "at least 1 target" in r.get_json()["error"]

    # Exceeding 5 targets
    r = client.post(
        "/api/comparisons",
        json={
            "adaptation_id": "rain_garden",
            "reference_location": {"latitude": 18.5204, "longitude": 73.8567},
            "targets": [{"latitude": 18.0 + i, "longitude": 73.0} for i in range(6)],
        },
    )
    assert r.status_code == 400
    assert "cannot exceed 5" in r.get_json()["error"]

    # Invalid target coordinate
    r = client.post(
        "/api/comparisons",
        json={
            "adaptation_id": "rain_garden",
            "reference_location": {"latitude": 18.5204, "longitude": 73.8567},
            "targets": [
                {"name": "Valid Target", "latitude": 18.6298, "longitude": 73.7997},
                {"name": "Bad Target", "latitude": 999.0, "longitude": 73.7997},
            ],
        },
    )
    assert r.status_code == 400
    assert "Target #2" in r.get_json()["error"]


def test_post_comparisons_successful_ranking(client):
    """
    Test comparing Pune against Pimpri, Niphad, Lonavala, and Nashik using sample CSV.
    Expected statuses in sample CSV:
      - Pimpri: suitable (score 1.0)
      - Nashik: conditional (open space = 0)
      - Lonavala: insufficient_data (soil_infiltration is NULL)
      - Niphad: unsuitable (slope = 12% > 8%)
    Ranking order must be: suitable (#1) -> conditional (#2) -> insufficient_data (#3) -> unsuitable (#4).
    """
    payload = {
        "adaptation_id": "rain_garden",
        "reference_location": {
            "name": "Pune Reference",
            "latitude": 18.5204,
            "longitude": 73.8567,
        },
        "targets": [
            {"name": "Niphad Site", "latitude": 20.0798, "longitude": 74.1069},
            {"name": "Pimpri Site", "latitude": 18.6298, "longitude": 73.7997},
            {"name": "Lonavala Site", "latitude": 18.7546, "longitude": 73.4062},
            {"name": "Nashik Site", "latitude": 19.9975, "longitude": 73.7898},
        ],
    }

    res = client.post("/api/comparisons", json=payload)
    assert res.status_code == 200
    data = res.get_json()

    assert data["adaptation_id"] == "rain_garden"
    assert data["reference_location"]["name"] == "Pune Reference"
    assert data["total_targets"] == 4
    targets = data["targets"]
    assert len(targets) == 4

    # Verify rank numbers are sequential 1..4
    assert [t["rank"] for t in targets] == [1, 2, 3, 4]

    # Verify rank ordering: Suitable -> Conditional -> Insufficient Data -> Unsuitable
    ranked_statuses = [t["status"] for t in targets]
    assert ranked_statuses == ["suitable", "conditional", "insufficient_data", "unsuitable"]

    # Verify #1 is Pimpri Site
    assert targets[0]["target_location"]["name"] == "Pimpri Site"
    assert targets[0]["score"] == 1.0
    assert targets[0]["limiting_factors"] == []

    # Verify #2 is Nashik Site
    assert targets[1]["target_location"]["name"] == "Nashik Site"
    assert targets[1]["status"] == "conditional"

    # Verify #3 is Lonavala Site
    assert targets[2]["target_location"]["name"] == "Lonavala Site"
    assert targets[2]["status"] == "insufficient_data"

    # Verify #4 is Niphad Site
    assert targets[3]["target_location"]["name"] == "Niphad Site"
    assert targets[3]["status"] == "unsuitable"
    assert any("slope" in lf.lower() for lf in targets[3]["limiting_factors"])

    # Verify each assessment was stored in the database
    for t in targets:
        assert isinstance(t["assessment_id"], int)
        get_res = client.get(f"/api/assessments/{t['assessment_id']}")
        assert get_res.status_code == 200


def test_compare_page_route(client):
    res = client.get("/compare")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "Compare Candidate Sites" in html
    assert "decision-support prototype" in html  # PRD §13 disclaimer
    assert "targetSitesContainer" in html
    assert "btnRunComparison" in html
    assert "leaderboardTable" in html


# --------------------------------------------------------------------------- #
# PDF Export Tests (FR-12)                                                    #
# --------------------------------------------------------------------------- #

def test_export_assessment_pdf_success(client):
    # 1. Create an assessment first
    create_res = client.post(
        "/api/assessments",
        json={
            "adaptation_id": "rain_garden",
            "reference_location": {
                "name": "Pune Reference",
                "latitude": 18.5204,
                "longitude": 73.8567,
            },
            "target_location": {
                "name": "Pimpri Candidate",
                "latitude": 18.6298,
                "longitude": 73.7997,
            },
        },
    )
    assert create_res.status_code == 201
    aid = create_res.get_json()["assessment_id"]

    # 2. Export assessment to PDF
    pdf_res = client.get(f"/api/assessments/{aid}/pdf")
    assert pdf_res.status_code == 200
    assert "application/pdf" in pdf_res.content_type
    assert f"ADAPTFIT_Assessment_{aid}.pdf" in pdf_res.headers.get("Content-Disposition", "")

    # Validate PDF signature and length
    assert len(pdf_res.data) > 1000
    assert pdf_res.data.startswith(b"%PDF-")


def test_export_assessment_pdf_not_found(client):
    res = client.get("/api/assessments/999999/pdf")
    assert res.status_code == 404
    assert "not found" in res.get_json()["error"].lower()


def test_results_page_contains_download_pdf_button(client):
    res = client.get("/results")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "downloadPdfBtn" in html
    assert "Download PDF" in html








