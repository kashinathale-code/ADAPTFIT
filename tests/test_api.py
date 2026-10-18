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
    # Environmental values in sample dataset are blank, so values are null
    for factor in ("annual_rainfall", "slope", "soil_infiltration"):
        assert factor in data["factors"]
        assert data["factors"][factor]["value"] is None


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


def test_get_assessment_not_found(client):
    res = client.get("/api/assessments/999999")
    assert res.status_code == 404
    assert "error" in res.get_json()
