from collections.abc import Generator
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.dependencies import get_open_meteo_client, get_wikimedia_client
from app.errors import LocationNotFoundError, UpstreamTimeoutError
from app.main import create_app
from app.schemas import NearbyPlaceResponse
from app.services.open_meteo import (
    DailyWeather,
    GeocodedLocation,
    OpenMeteoClient,
    WeatherSnapshot,
)


class FakeOpenMeteoClient:
    def __init__(self) -> None:
        self.resolve_calls = 0
        self.weather_calls = 0

    def validate_date_range(self, start_date: date, end_date: date) -> None:
        OpenMeteoClient(Settings()).validate_date_range(start_date, end_date)

    async def resolve_location(self, location: str) -> GeocodedLocation:
        self.resolve_calls += 1
        if location.casefold() == "atlantis":
            raise LocationNotFoundError(location)
        if location.casefold() == "timeout city":
            raise UpstreamTimeoutError("Open-Meteo")
        is_rabat = location.casefold() == "rabat"
        return self._location(location, is_rabat=is_rabat)

    async def search_locations(self, location: str) -> list[GeocodedLocation]:
        self.resolve_calls += 1
        if location.casefold() == "atlantis":
            return []
        return [
            self._location(location, is_rabat=False),
            GeocodedLocation(
                original=location,
                canonical="Casablanca, Centre-Val de Loire, France",
                latitude=47.115,
                longitude=1.35,
                timezone="Europe/Paris",
                country_code="FR",
                admin1="Centre-Val de Loire",
                match_type="fuzzy",
                location_id=222,
                name="Casablanca",
                country="France",
            ),
        ]

    async def resolve_location_id(
        self, location_id: int, original: str
    ) -> GeocodedLocation:
        self.resolve_calls += 1
        if location_id == 222:
            return GeocodedLocation(
                original=original,
                canonical="Casablanca, Centre-Val de Loire, France",
                latitude=47.115,
                longitude=1.35,
                timezone="Europe/Paris",
                country_code="FR",
                admin1="Centre-Val de Loire",
                match_type="selected",
                location_id=222,
                name="Casablanca",
                country="France",
            )
        return self._location(original, is_rabat=location_id == 202)

    def _location(self, original: str, is_rabat: bool) -> GeocodedLocation:
        return GeocodedLocation(
            original=original,
            canonical="Rabat, Rabat-Salé-Kénitra, Morocco" if is_rabat else "Casablanca, Casablanca-Settat, Morocco",
            latitude=34.0133 if is_rabat else 33.5731,
            longitude=-6.8326 if is_rabat else -7.5898,
            timezone="Africa/Casablanca",
            country_code="MA",
            admin1="Rabat-Salé-Kénitra" if is_rabat else "Casablanca-Settat",
            match_type="exact",
            alternatives=["Casablanca, Settat, Morocco"],
            location_id=202 if is_rabat else 101,
            name="Rabat" if is_rabat else "Casablanca",
            country="Morocco",
        )

    async def fetch_weather(
        self, location: GeocodedLocation, start_date: date, end_date: date
    ) -> WeatherSnapshot:
        self.weather_calls += 1
        days = []
        current = start_date
        index = 0
        while current <= end_date:
            days.append(
                DailyWeather(
                    weather_date=current,
                    temperature_mean_c=24.0 + index,
                    temperature_min_c=19.0 + index,
                    temperature_max_c=29.0 + index,
                    apparent_temperature_mean_c=25.0 + index,
                    precipitation_sum_mm=0.2 * index,
                    precipitation_probability_max_pct=10.0 + index,
                    humidity_mean_pct=62.0,
                    wind_speed_max_kmh=22.0,
                    weather_code=1,
                    weather_description="Mainly clear",
                )
            )
            current += timedelta(days=1)
            index += 1
        return WeatherSnapshot(
            timezone="Africa/Casablanca",
            retrieved_at=datetime.now(timezone.utc),
            days=days,
        )


class FakeWikimediaClient:
    def __init__(self) -> None:
        self.calls = 0

    async def nearby_places(
        self, latitude: float, longitude: float, radius_m: int, limit: int
    ) -> list[NearbyPlaceResponse]:
        self.calls += 1
        return [
            NearbyPlaceResponse(
                page_id=123,
                title="Hassan II Mosque",
                latitude=33.6084,
                longitude=-7.6326,
                distance_m=4200.0,
                article_url="https://en.wikipedia.org/wiki/Hassan_II_Mosque",
            )
        ][:limit]


@dataclass
class ApiTestContext:
    client: TestClient
    weather: FakeOpenMeteoClient
    wikimedia: FakeWikimediaClient
    database_path: Path


@pytest.fixture
def context(tmp_path: Path) -> Generator[ApiTestContext, None, None]:
    database_path = tmp_path / "test-weather.db"
    settings = Settings(database_url=f"sqlite:///{database_path.as_posix()}")
    application = create_app(settings)
    fake_weather = FakeOpenMeteoClient()
    fake_wikimedia = FakeWikimediaClient()
    application.dependency_overrides[get_open_meteo_client] = lambda: fake_weather
    application.dependency_overrides[get_wikimedia_client] = lambda: fake_wikimedia
    with TestClient(application) as client:
        yield ApiTestContext(client, fake_weather, fake_wikimedia, database_path)


@pytest.fixture
def valid_payload() -> dict[str, str]:
    today = date.today()
    return {
        "location": "Casablanca",
        "start_date": today.isoformat(),
        "end_date": (today + timedelta(days=1)).isoformat(),
    }
