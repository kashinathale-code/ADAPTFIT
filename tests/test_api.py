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
    # Assessment with blank CSV sample data -> should produce insufficient_data
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


