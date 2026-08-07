import asyncio
from datetime import date

import httpx
import pytest

from app.config import Settings
from app.errors import UpstreamDataError, UpstreamServiceError
from app.services.open_meteo import OpenMeteoClient
from app.services.wikimedia import WikimediaClient


def test_open_meteo_converts_upstream_5xx_to_safe_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"reason": "maintenance"})

    client = OpenMeteoClient(Settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(UpstreamServiceError) as caught:
        asyncio.run(client.resolve_location("Casablanca"))
    assert caught.value.status_code == 502
    assert caught.value.details == {"provider": "Open-Meteo", "upstream_status": 503}


def test_open_meteo_rejects_malformed_geocoding_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": "not-a-list"})

    client = OpenMeteoClient(Settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(UpstreamDataError):
        asyncio.run(client.resolve_location("Casablanca"))


def test_open_meteo_parses_geocoding_and_weather_payloads() -> None:
    today = date.today()

    def handler(request: httpx.Request) -> httpx.Response:
        if "geocoding" in request.url.host:
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "name": "Casablanca",
                            "latitude": 33.5731,
                            "longitude": -7.5898,
                            "timezone": "Africa/Casablanca",
                            "country_code": "MA",
                            "country": "Morocco",
                            "admin1": "Casablanca-Settat",
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "timezone": "Africa/Casablanca",
                "daily": {
                    "time": [today.isoformat()],
                    "weather_code": [1],
                    "temperature_2m_mean": [24.5],
                    "temperature_2m_min": [20.0],
                    "temperature_2m_max": [29.0],
                    "apparent_temperature_mean": [25.1],
                    "precipitation_sum": [0.0],
                    "precipitation_probability_max": [5],
                    "relative_humidity_2m_mean": [63],
                    "wind_speed_10m_max": [21.4],
                },
            },
        )

    client = OpenMeteoClient(Settings(), transport=httpx.MockTransport(handler))

    async def run() -> None:
        location = await client.resolve_location("Casablanca")
        snapshot = await client.fetch_weather(location, today, today)
        assert location.canonical == "Casablanca, Casablanca-Settat, Morocco"
        assert snapshot.days[0].temperature_mean_c == 24.5
        assert snapshot.days[0].weather_description == "Mainly clear"

    asyncio.run(run())


def test_open_meteo_resolves_selected_location_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["id"] == "101"
        return httpx.Response(
            200,
            json={
                "id": 101,
                "name": "Casablanca",
                "latitude": 33.5731,
                "longitude": -7.5898,
                "timezone": "Africa/Casablanca",
                "country_code": "MA",
                "country": "Morocco",
                "admin1": "Casablanca-Settat",
            },
        )

    client = OpenMeteoClient(Settings(), transport=httpx.MockTransport(handler))
    location = asyncio.run(client.resolve_location_id(101, "Casablanca"))
    assert location.location_id == 101
    assert location.match_type == "selected"
    assert location.canonical == "Casablanca, Casablanca-Settat, Morocco"


def test_wikimedia_parses_nearby_places() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["user-agent"].startswith("PMA-Weather-Assessment")
        return httpx.Response(
            200,
            json={
                "query": {
                    "geosearch": [
                        {
                            "pageid": 123,
                            "title": "Hassan II Mosque",
                            "lat": 33.6084,
                            "lon": -7.6326,
                            "dist": 4200.0,
                        }
                    ]
                }
            },
        )

    client = WikimediaClient(Settings(), transport=httpx.MockTransport(handler))
    places = asyncio.run(client.nearby_places(33.5731, -7.5898, 10_000, 5))
    assert places[0].title == "Hassan II Mosque"
    assert places[0].article_url.endswith("Hassan_II_Mosque")
