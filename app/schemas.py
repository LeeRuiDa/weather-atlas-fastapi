from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _clean_location(value: str) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError("location must not be empty")
    return normalized


class WeatherCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "location": "Casablanca",
                    "start_date": "2026-08-06",
                    "end_date": "2026-08-08",
                }
            ]
        }
    )

    location: str = Field(
        min_length=2,
        max_length=200,
        description="City, town, or postal-code text supplied by the user.",
        examples=["Casablanca"],
    )
    location_id: int | None = Field(
        default=None,
        gt=0,
        description="Optional Open-Meteo candidate ID selected from /locations/search.",
    )
    start_date: date = Field(description="First requested weather date (inclusive).")
    end_date: date = Field(description="Last requested weather date (inclusive).")

    _normalize_location = field_validator("location")(_clean_location)

    @model_validator(mode="after")
    def validate_dates(self) -> "WeatherCreate":
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class WeatherPatch(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"location": "Rabat"},
                {"start_date": "2026-08-07", "end_date": "2026-08-09"},
            ]
        }
    )

    location: str | None = Field(default=None, min_length=2, max_length=200)
    location_id: int | None = Field(default=None, gt=0)
    start_date: date | None = None
    end_date: date | None = None

    @field_validator("location")
    @classmethod
    def normalize_optional_location(cls, value: str | None) -> str | None:
        return _clean_location(value) if value is not None else None

    @model_validator(mode="after")
    def require_change(self) -> "WeatherPatch":
        if (
            self.location is None
            and self.location_id is None
            and self.start_date is None
            and self.end_date is None
        ):
            raise ValueError(
                "provide at least one of location, location_id, start_date, or end_date"
            )
        if self.location_id is not None and self.location is None:
            raise ValueError("location is required when location_id is provided")
        return self


class LocationCandidateResponse(BaseModel):
    location_id: int
    name: str
    canonical_location: str
    country: str | None
    country_code: str | None
    admin1: str | None
    latitude: float
    longitude: float
    timezone: str


class LocationSearchResponse(BaseModel):
    query: str
    candidates: list[LocationCandidateResponse]


class WeatherDayResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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


class WeatherRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    original_location: str
    canonical_location: str
    country_code: str | None
    admin1: str | None
    latitude: float
    longitude: float
    timezone: str
    location_match: str
    start_date: date
    end_date: date
    retrieved_at: datetime
    created_at: datetime
    updated_at: datetime
    days: list[WeatherDayResponse]


class WeatherListResponse(BaseModel):
    items: list[WeatherRecordResponse]
    total: int
    offset: int
    limit: int


class NearbyPlaceResponse(BaseModel):
    page_id: int
    title: str
    latitude: float
    longitude: float
    distance_m: float
    article_url: str


class NearbyResponse(BaseModel):
    weather_record_id: int
    canonical_location: str
    radius_m: int
    places: list[NearbyPlaceResponse]


class OutingScoreBreakdown(BaseModel):
    precipitation: float
    weather_condition: float
    temperature_comfort: float
    wind: float
    missing_data: float


class OutingDayAssessment(BaseModel):
    weather_date: date
    score: int = Field(ge=0, le=100)
    weather_description: str
    apparent_temperature_mean_c: float | None
    precipitation_sum_mm: float | None
    precipitation_probability_max_pct: float | None
    wind_speed_max_kmh: float | None
    penalties: OutingScoreBreakdown
    reasons: list[str]


class OutingPlanResponse(BaseModel):
    weather_record_id: int
    canonical_location: str
    best_day: OutingDayAssessment
    daily_scores: list[OutingDayAssessment]
    summary: str
    methodology: str = Field(
        description="Plain-language scoring rules; this is deterministic, not AI/ML."
    )
    radius_m: int
    nearby_places: list[NearbyPlaceResponse]


class ExportFormat(str, Enum):
    json = "json"
    csv = "csv"


class ErrorEnvelope(BaseModel):
    error: dict[str, Any]
