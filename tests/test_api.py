import csv
import io
from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.config import Settings
from app.dependencies import get_open_meteo_client, get_wikimedia_client
from app.errors import UpstreamTimeoutError
from app.main import create_app
from tests.conftest import ApiTestContext, FakeOpenMeteoClient, FakeWikimediaClient


def create_record(context: ApiTestContext, payload: dict[str, str]) -> dict:
    response = context.client.post("/weather", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_health_root_about_and_openapi(context: ApiTestContext) -> None:
    assert context.client.get("/health").json() == {"status": "ok"}
    root = context.client.get("/")
    assert root.status_code == 200
    assert root.json()["candidate"] == "Rida Boubakr"
    assert "Backend Tech Assessment #2" in root.json()["assessment"]
    about = context.client.get("/about")
    assert about.status_code == 200
    assert "Product Manager Accelerator" in about.json()["pm_accelerator"]
    assert about.json()["pm_accelerator_linkedin"].startswith("https://www.linkedin.com/")
    assert "/weather/export" in context.client.get("/openapi.json").json()["paths"]


def test_dashboard_and_static_assets_load(context: ApiTestContext) -> None:
    dashboard = context.client.get("/dashboard")
    assert dashboard.status_code == 200
    assert dashboard.headers["content-type"].startswith("text/html")
    assert 'id="weather-form"' in dashboard.text
    assert "Weather Atlas" in dashboard.text

    stylesheet = context.client.get("/static/dashboard.css")
    script = context.client.get("/static/dashboard.js")
    assert stylesheet.status_code == 200
    assert stylesheet.headers["content-type"].startswith("text/css")
    assert script.status_code == 200
    assert "loadOutingPlan" in script.text


def test_openapi_documents_bonus_endpoints_and_errors(context: ApiTestContext) -> None:
    schema = context.client.get("/openapi.json").json()
    assert schema["info"]["version"] == "1.1.0"
    assert {tag["name"] for tag in schema["tags"]} == {"meta", "locations", "weather"}
    assert schema["paths"]["/weather"]["post"]["summary"] == (
        "Create and persist a weather snapshot"
    )
    assert "502" in schema["paths"]["/weather"]["post"]["responses"]
    assert "/locations/search" in schema["paths"]
    assert "/weather/{record_id}/outing-plan" in schema["paths"]


def test_location_search_exposes_ranked_candidates(context: ApiTestContext) -> None:
    response = context.client.get("/locations/search?query=Casablanca")
    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "Casablanca"
    assert len(body["candidates"]) == 2
    assert body["candidates"][0]["location_id"] == 101
    assert body["candidates"][0]["country"] == "Morocco"
    assert body["candidates"][1]["admin1"] == "Centre-Val de Loire"


def test_create_can_use_deliberately_selected_location(
    context: ApiTestContext, valid_payload: dict[str, str]
) -> None:
    response = context.client.post(
        "/weather", json={**valid_payload, "location_id": 222}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["canonical_location"] == "Casablanca, Centre-Val de Loire, France"
    assert body["country_code"] == "FR"
    assert body["location_match"] == "selected"


def test_update_can_use_deliberately_selected_location(
    context: ApiTestContext, valid_payload: dict[str, str]
) -> None:
    created = create_record(context, valid_payload)
    response = context.client.patch(
        f"/weather/{created['id']}",
        json={"location": "Casablanca", "location_id": 222},
    )
    assert response.status_code == 200, response.text
    assert response.json()["canonical_location"].endswith("France")
    assert response.json()["location_match"] == "selected"


def test_create_and_read_list(context: ApiTestContext, valid_payload: dict[str, str]) -> None:
    created = create_record(context, valid_payload)
    assert created["id"] == 1
    assert created["original_location"] == "Casablanca"
    assert created["canonical_location"].startswith("Casablanca")
    assert len(created["days"]) == 2
    assert created["days"][0]["temperature_mean_c"] == 24.0

    fetched = context.client.get("/weather/1")
    assert fetched.status_code == 200
    assert fetched.json() == created
    listed = context.client.get("/weather")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["id"] == 1


def test_invalid_date_range(context: ApiTestContext, valid_payload: dict[str, str]) -> None:
    invalid = dict(valid_payload)
    invalid["start_date"], invalid["end_date"] = invalid["end_date"], invalid["start_date"]
    response = context.client.post("/weather", json=invalid)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert context.weather.resolve_calls == 0


def test_provider_date_window_is_enforced_before_api_call(
    context: ApiTestContext, valid_payload: dict[str, str]
) -> None:
    today = date.fromisoformat(valid_payload["start_date"])
    response = context.client.post(
        "/weather",
        json={
            "location": "Casablanca",
            "start_date": (today - timedelta(days=16)).isoformat(),
            "end_date": today.isoformat(),
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "date_range_not_supported"
    assert response.json()["error"]["details"]["maximum_range_days"] == 16
    assert context.weather.resolve_calls == 0


def test_invalid_and_empty_location(context: ApiTestContext, valid_payload: dict[str, str]) -> None:
    empty = context.client.post("/weather", json={**valid_payload, "location": "   "})
    assert empty.status_code == 422
    assert empty.json()["error"]["code"] == "validation_error"

    missing = context.client.post("/weather", json={**valid_payload, "location": "Atlantis"})
    assert missing.status_code == 422
    assert missing.json()["error"]["code"] == "location_not_found"


def test_read_missing_id(context: ApiTestContext) -> None:
    response = context.client.get("/weather/999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "weather_record_not_found"


def test_update_refetches_and_replaces_snapshot(
    context: ApiTestContext, valid_payload: dict[str, str]
) -> None:
    created = create_record(context, valid_payload)
    new_end = (date.fromisoformat(valid_payload["start_date"]) + timedelta(days=2)).isoformat()
    response = context.client.patch(
        f"/weather/{created['id']}", json={"location": "Rabat", "end_date": new_end}
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["original_location"] == "Rabat"
    assert updated["canonical_location"].startswith("Rabat")
    assert len(updated["days"]) == 3
    assert context.weather.resolve_calls == 2
    assert context.weather.weather_calls == 2


def test_update_validates_merged_date_range(
    context: ApiTestContext, valid_payload: dict[str, str]
) -> None:
    created = create_record(context, valid_payload)
    later = (date.fromisoformat(valid_payload["end_date"]) + timedelta(days=1)).isoformat()
    response = context.client.patch(f"/weather/{created['id']}", json={"start_date": later})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "date_range_not_supported"
    unchanged = context.client.get(f"/weather/{created['id']}").json()
    assert unchanged["start_date"] == valid_payload["start_date"]


def test_delete_and_delete_missing(context: ApiTestContext, valid_payload: dict[str, str]) -> None:
    created = create_record(context, valid_payload)
    deleted = context.client.delete(f"/weather/{created['id']}")
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert context.client.get(f"/weather/{created['id']}").status_code == 404
    missing = context.client.delete("/weather/999")
    assert missing.status_code == 404


def test_upstream_timeout_is_safe_and_not_persisted(
    context: ApiTestContext, valid_payload: dict[str, str]
) -> None:
    response = context.client.post(
        "/weather", json={**valid_payload, "location": "Timeout City"}
    )
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "upstream_timeout"
    assert context.client.get("/weather").json()["total"] == 0


def test_json_and_csv_export(context: ApiTestContext, valid_payload: dict[str, str]) -> None:
    create_record(context, valid_payload)
    json_response = context.client.get("/weather/export?format=json")
    assert json_response.status_code == 200
    assert json_response.headers["content-type"].startswith("application/json")
    assert json_response.headers["content-disposition"].endswith('.json"')
    assert json_response.json()[0]["id"] == 1

    csv_response = context.client.get("/weather/export?format=csv")
    assert csv_response.status_code == 200
    assert csv_response.headers["content-type"].startswith("text/csv")
    assert csv_response.headers["content-disposition"].endswith('.csv"')
    rows = list(csv.DictReader(io.StringIO(csv_response.text)))
    assert len(rows) == 2
    assert rows[0]["canonical_location"].startswith("Casablanca")
    assert rows[0]["weather_description"] == "Mainly clear"


def test_unsupported_export_format(context: ApiTestContext) -> None:
    response = context.client.get("/weather/export?format=xml")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_nearby_places_integration(context: ApiTestContext, valid_payload: dict[str, str]) -> None:
    created = create_record(context, valid_payload)
    response = context.client.get(f"/weather/{created['id']}/nearby?radius_m=5000&limit=3")
    assert response.status_code == 200
    body = response.json()
    assert body["radius_m"] == 5000
    assert body["places"][0]["title"] == "Hassan II Mosque"
    assert body["places"][0]["article_url"].startswith("https://en.wikipedia.org/")
    assert context.wikimedia.calls == 1


def test_outing_plan_combines_weather_and_nearby_places(
    context: ApiTestContext, valid_payload: dict[str, str]
) -> None:
    created = create_record(context, valid_payload)
    response = context.client.get(f"/weather/{created['id']}/outing-plan")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["best_day"]["weather_date"] == valid_payload["start_date"]
    assert body["best_day"]["score"] > body["daily_scores"][1]["score"]
    assert body["nearby_places"][0]["title"] == "Hassan II Mosque"
    assert "Scores start at 100" in body["methodology"]
    assert "/100 suitability score" in body["summary"]


def test_outing_plan_propagates_safe_nearby_timeout(
    context: ApiTestContext, valid_payload: dict[str, str]
) -> None:
    class TimeoutWikimediaClient:
        async def nearby_places(self, *args, **kwargs):
            raise UpstreamTimeoutError("Wikimedia")

    created = create_record(context, valid_payload)
    context.client.app.dependency_overrides[get_wikimedia_client] = (
        lambda: TimeoutWikimediaClient()
    )
    response = context.client.get(f"/weather/{created['id']}/outing-plan")
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "upstream_timeout"


def test_sqlite_persists_across_app_restart(tmp_path, valid_payload: dict[str, str]) -> None:
    database_path = tmp_path / "persistent.db"
    settings = Settings(database_url=f"sqlite:///{database_path.as_posix()}")

    first_app = create_app(settings)
    first_weather = FakeOpenMeteoClient()
    first_app.dependency_overrides[get_open_meteo_client] = lambda: first_weather
    first_app.dependency_overrides[get_wikimedia_client] = lambda: FakeWikimediaClient()
    with TestClient(first_app) as first_client:
        assert first_client.post("/weather", json=valid_payload).status_code == 201

    second_app = create_app(settings)
    second_app.dependency_overrides[get_open_meteo_client] = lambda: FakeOpenMeteoClient()
    second_app.dependency_overrides[get_wikimedia_client] = lambda: FakeWikimediaClient()
    with TestClient(second_app) as second_client:
        response = second_client.get("/weather/1")
        assert response.status_code == 200
        assert len(response.json()["days"]) == 2
