from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from numbers import Real
from typing import Any

import httpx

from app.config import Settings
from app.errors import (
    DateRangeNotSupportedError,
    LocationNotFoundError,
    UpstreamDataError,
    UpstreamServiceError,
    UpstreamTimeoutError,
)


@dataclass(frozen=True)
class GeocodedLocation:
    original: str
    canonical: str
    latitude: float
    longitude: float
    timezone: str
    country_code: str | None
    admin1: str | None
    match_type: str
    alternatives: list[str] = field(default_factory=list)
    location_id: int | None = None
    name: str = ""
    country: str | None = None


@dataclass(frozen=True)
class DailyWeather:
    weather_date: date
    temperature_mean_c: float | None
    temperature_min_c: float | None
    temperature_max_c: float | None
    apparent_temperature_mean_c: float | None
    precipitation_sum_mm: float | None
    precipitation_probability_max_pct: float | None
    humidity_mean_pct: float | None
    wind_speed_max_kmh: float | None
    weather_code: int | None
    weather_description: str


@dataclass(frozen=True)
class WeatherSnapshot:
    timezone: str
    retrieved_at: datetime
    days: list[DailyWeather]


WMO_DESCRIPTIONS = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


class OpenMeteoClient:
    provider_name = "Open-Meteo"

    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport

    async def _get_json(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.external_api_timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise UpstreamTimeoutError(self.provider_name) from exc
        except httpx.HTTPStatusError as exc:
            raise UpstreamServiceError(
                self.provider_name, exc.response.status_code
            ) from exc
        except httpx.RequestError as exc:
            raise UpstreamServiceError(self.provider_name) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise UpstreamDataError(self.provider_name) from exc
        if not isinstance(payload, dict):
            raise UpstreamDataError(self.provider_name)
        return payload

    async def resolve_location(self, location: str) -> GeocodedLocation:
        candidates = await self.search_locations(location)
        if not candidates:
            raise LocationNotFoundError(" ".join(location.split()))
        selected = candidates[0]
        return replace(
            selected,
            alternatives=[candidate.canonical for candidate in candidates[1:4]],
        )

    async def search_locations(self, location: str) -> list[GeocodedLocation]:
        normalized = " ".join(location.split())
        payload = await self._get_json(
            self.settings.open_meteo_geocoding_url,
            {"name": normalized, "count": 5, "language": "en", "format": "json"},
        )
        results = payload.get("results")

        # Users often enter "City, Country" while the provider ranks by locality name.
        if not results and "," in normalized:
            locality = normalized.split(",", maxsplit=1)[0].strip()
            if len(locality) >= 2:
                payload = await self._get_json(
                    self.settings.open_meteo_geocoding_url,
                    {"name": locality, "count": 5, "language": "en", "format": "json"},
                )
                results = payload.get("results")

        if results is None:
            results = []
        if not isinstance(results, list):
            raise UpstreamDataError(self.provider_name)
        if not results:
            return []

        return [self._parse_location(item, normalized) for item in results]

    async def resolve_location_id(
        self, location_id: int, original: str
    ) -> GeocodedLocation:
        normalized = " ".join(original.split())
        payload = await self._get_json(
            self.settings.open_meteo_geocoding_get_url,
            {"id": location_id},
        )
        item: Any = payload
        if isinstance(payload.get("results"), list):
            results = payload["results"]
            item = results[0] if results else None
        if not isinstance(item, dict) or "name" not in item:
            raise LocationNotFoundError(normalized)
        candidate = self._parse_location(item, normalized)
        if candidate.location_id is not None and candidate.location_id != location_id:
            raise UpstreamDataError(self.provider_name)
        return replace(candidate, match_type="selected", alternatives=[])

    def _parse_location(self, item: Any, original: str) -> GeocodedLocation:
        if not isinstance(item, dict):
            raise UpstreamDataError(self.provider_name)
        name = item.get("name")
        latitude = item.get("latitude")
        longitude = item.get("longitude")
        if (
            not isinstance(name, str)
            or not isinstance(latitude, Real)
            or isinstance(latitude, bool)
            or not isinstance(longitude, Real)
            or isinstance(longitude, bool)
        ):
            raise UpstreamDataError(self.provider_name)

        admin1 = item.get("admin1") if isinstance(item.get("admin1"), str) else None
        country = item.get("country") if isinstance(item.get("country"), str) else None
        country_code = (
            item.get("country_code") if isinstance(item.get("country_code"), str) else None
        )
        location_id = (
            item.get("id")
            if isinstance(item.get("id"), int)
            and not isinstance(item.get("id"), bool)
            and item.get("id") > 0
            else None
        )
        timezone_name = (
            item.get("timezone") if isinstance(item.get("timezone"), str) else "auto"
        )
        parts: list[str] = []
        for part in (name, admin1, country):
            if part and part.casefold() not in {existing.casefold() for existing in parts}:
                parts.append(part)
        canonical = ", ".join(parts)
        query = original.casefold()
        match_type = (
            "exact"
            if query == name.casefold()
            or query == canonical.casefold()
            or query.startswith(f"{name.casefold()},")
            else "fuzzy"
        )
        return GeocodedLocation(
            original=original,
            canonical=canonical,
            latitude=float(latitude),
            longitude=float(longitude),
            timezone=timezone_name,
            country_code=country_code,
            admin1=admin1,
            match_type=match_type,
            location_id=location_id,
            name=name,
            country=country,
        )

    def validate_date_range(self, start_date: date, end_date: date) -> None:
        today = date.today()
        earliest = today - timedelta(days=self.settings.weather_past_days)
        latest = today + timedelta(days=self.settings.weather_future_days)
        requested_days = (end_date - start_date).days + 1
        details = {
            "earliest_supported_date": earliest.isoformat(),
            "latest_supported_date": latest.isoformat(),
            "maximum_range_days": self.settings.max_date_range_days,
        }
        if end_date < start_date:
            raise DateRangeNotSupportedError(
                "end_date must be on or after start_date.", details
            )
        if requested_days > self.settings.max_date_range_days:
            raise DateRangeNotSupportedError(
                f"Date ranges may contain at most {self.settings.max_date_range_days} days.",
                details,
            )
        if start_date < earliest or end_date > latest:
            raise DateRangeNotSupportedError(
                "The requested dates fall outside Open-Meteo's supported forecast window.",
                details,
            )

    async def fetch_weather(
        self, location: GeocodedLocation, start_date: date, end_date: date
    ) -> WeatherSnapshot:
        self.validate_date_range(start_date, end_date)
        daily_fields = [
            "weather_code",
            "temperature_2m_mean",
            "temperature_2m_min",
            "temperature_2m_max",
            "apparent_temperature_mean",
            "precipitation_sum",
            "precipitation_probability_max",
            "relative_humidity_2m_mean",
            "wind_speed_10m_max",
        ]
        payload = await self._get_json(
            self.settings.open_meteo_forecast_url,
            {
                "latitude": location.latitude,
                "longitude": location.longitude,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "daily": ",".join(daily_fields),
                "timezone": "auto",
                "temperature_unit": "celsius",
                "wind_speed_unit": "kmh",
                "precipitation_unit": "mm",
            },
        )
        daily = payload.get("daily")
        if not isinstance(daily, dict):
            raise UpstreamDataError(self.provider_name)
        expected_length = (end_date - start_date).days + 1
        for field_name in ["time", *daily_fields]:
            values = daily.get(field_name)
            if not isinstance(values, list) or len(values) != expected_length:
                raise UpstreamDataError(self.provider_name)

        days: list[DailyWeather] = []
        for index in range(expected_length):
            try:
                weather_date = date.fromisoformat(daily["time"][index])
            except (TypeError, ValueError) as exc:
                raise UpstreamDataError(self.provider_name) from exc
            code = self._optional_int(daily["weather_code"][index])
            days.append(
                DailyWeather(
                    weather_date=weather_date,
                    temperature_mean_c=self._optional_float(
                        daily["temperature_2m_mean"][index]
                    ),
                    temperature_min_c=self._optional_float(
                        daily["temperature_2m_min"][index]
                    ),
                    temperature_max_c=self._optional_float(
                        daily["temperature_2m_max"][index]
                    ),
                    apparent_temperature_mean_c=self._optional_float(
                        daily["apparent_temperature_mean"][index]
                    ),
                    precipitation_sum_mm=self._optional_float(
                        daily["precipitation_sum"][index]
                    ),
                    precipitation_probability_max_pct=self._optional_float(
                        daily["precipitation_probability_max"][index]
                    ),
                    humidity_mean_pct=self._optional_float(
                        daily["relative_humidity_2m_mean"][index]
                    ),
                    wind_speed_max_kmh=self._optional_float(
                        daily["wind_speed_10m_max"][index]
                    ),
                    weather_code=code,
                    weather_description=WMO_DESCRIPTIONS.get(code, "Unknown"),
                )
            )
        timezone_name = payload.get("timezone")
        if not isinstance(timezone_name, str):
            raise UpstreamDataError(self.provider_name)
        return WeatherSnapshot(
            timezone=timezone_name,
            retrieved_at=datetime.now(timezone.utc),
            days=days,
        )

    def _optional_float(self, value: Any) -> float | None:
        if value is None:
            return None
        if not isinstance(value, Real) or isinstance(value, bool):
            raise UpstreamDataError(self.provider_name)
        return float(value)

    def _optional_int(self, value: Any) -> int | None:
        if value is None:
            return None
        if not isinstance(value, Real) or isinstance(value, bool):
            raise UpstreamDataError(self.provider_name)
        return int(value)
