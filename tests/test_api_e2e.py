import pytest
from fastapi.testclient import TestClient

from fleetlens.api import create_app
from fleetlens.config import Settings

pytestmark = pytest.mark.e2e


def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_request_id_is_generated_and_propagated(client):
    assert len(client.get("/health").headers["X-Request-ID"]) == 16
    r = client.get("/health", headers={"X-Request-ID": "trace-abc"})
    assert r.headers["X-Request-ID"] == "trace-abc"


def test_metrics_use_route_templates(client):
    client.get("/vehicles/1")
    client.get("/vehicles/2")
    body = client.get("/metrics").text
    assert 'route="/vehicles/{vehicle_id}"' in body
    assert 'route="/vehicles/1"' not in body


def test_list_vehicles_filters(client):
    r = client.get("/vehicles", params={"gm_only": True, "limit": 10})
    assert r.status_code == 200
    page = r.json()
    assert page["limit"] == 10 and len(page["items"]) <= 10
    assert all(v["is_gm_brand"] for v in page["items"])


def test_list_vehicles_rejects_bad_ranges(client):
    assert client.get("/vehicles", params={"year_from": 2015, "year_to": 2010}).status_code == 422
    assert client.get("/vehicles", params={"limit": 0}).status_code == 422
    assert client.get("/vehicles", params={"powertrain": "steam"}).status_code == 422


def test_get_vehicle_and_404(client):
    r = client.get("/vehicles/9001")
    assert r.status_code == 200 and r.json()["powertrain"] == "electric"
    assert client.get("/vehicles/123456789").status_code == 404


def test_make_trend(client):
    r = client.get("/makes/chevrolet/trend")
    assert r.status_code == 200
    years = [p["year"] for p in r.json()]
    assert years == sorted(years)
    assert client.get("/makes/NoSuchMake/trend").status_code == 404


def test_fleet_estimate_end_to_end(client):
    body = {
        "items": [
            {"vehicle_id": 1, "quantity": 20, "annual_miles": 15000},
            {"vehicle_id": 9001, "quantity": 5},
        ],
        "fuel_price_usd_per_gallon": 3.25,
    }
    r = client.post("/fleet/estimate", json=body)
    assert r.status_code == 200
    data = r.json()
    assert data["totals"]["vehicles"] == 25
    ev_line = next(line for line in data["lines"] if line["vehicle_id"] == 9001)
    assert ev_line["co2_metric_tons"] == 0
    assert data["totals"]["fuel_cost_usd"] == pytest.approx(
        sum(line["fuel_cost_usd"] for line in data["lines"]), abs=0.01
    )


def test_fleet_estimate_unknown_vehicle(client):
    r = client.post("/fleet/estimate", json={"items": [{"vehicle_id": 424242}]})
    assert r.status_code == 404 and "424242" in r.json()["detail"]


def test_fleet_estimate_validation(client):
    assert client.post("/fleet/estimate", json={"items": []}).status_code == 422
    bad = {"items": [{"vehicle_id": 1, "quantity": -3}]}
    assert client.post("/fleet/estimate", json=bad).status_code == 422


def test_predict_mpg(client):
    body = {
        "year": 2014,
        "cylinders": 4,
        "displacement_l": 2.0,
        "drive": "FWD",
        "transmission": "automatic",
        "vehicle_class": "Compact Cars",
    }
    r = client.post("/predict/mpg", json=body)
    assert r.status_code == 200
    assert 5 < r.json()["predicted_combined_mpg"] < 80
    assert client.post("/predict/mpg", json={**body, "cylinders": 40}).status_code == 422


def test_data_quality_endpoint(client):
    r = client.get("/data-quality")
    assert r.status_code == 200 and r.json()["rows_rejected"] == 4


def test_openapi_contract_is_published(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert {"/vehicles", "/fleet/estimate", "/predict/mpg"} <= set(paths)


def test_degrades_gracefully_without_model(loaded_db, settings, tmp_path):
    s = Settings(
        db_path=settings.db_path,
        model_path=tmp_path / "missing.joblib",
        raw_csv_path=settings.raw_csv_path,
        source_url="",
        log_level="WARNING",
    )
    with TestClient(create_app(s)) as c:
        assert c.get("/health").json() == {
            "status": "degraded",
            "database": True,
            "model_loaded": False,
            "version": "1.0.0",
        }
        assert c.get("/vehicles/1").status_code == 200
        assert c.post("/predict/mpg", json={}).status_code in (422, 503)
