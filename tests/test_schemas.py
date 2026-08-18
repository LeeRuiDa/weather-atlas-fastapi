"""Unit tests for Pydantic request/response schemas.

Validates that the schema layer enforces the constraints documented in the
API (e.g. min-length, positive-only IDs, date ordering) and that the
whitespace-normalisation helper behaves correctly.
"""

from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from app.schemas import (
    ExportFormat,
    OutingDayAssessment,
    OutingScoreBreakdown,
    WeatherCreate,
    WeatherPatch,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
TODAY = date.today()
TOMORROW = TODAY + timedelta(days=1)


def _valid_create(**overrides: object) -> dict:
    """Return a minimal valid WeatherCreate payload, with optional overrides."""
    payload: dict = {
        "location": "Casablanca",
        "start_date": TODAY.isoformat(),
        "end_date": TOMORROW.isoformat(),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# WeatherCreate — happy path
# ---------------------------------------------------------------------------
class TestWeatherCreateValid:
    def test_minimal_valid_input(self) -> None:
        record = WeatherCreate(**_valid_create())
        assert record.location == "Casablanca"
        assert record.start_date == TODAY
        assert record.end_date == TOMORROW
        assert record.location_id is None

    def test_with_location_id(self) -> None:
        record = WeatherCreate(**_valid_create(location_id=42))
        assert record.location_id == 42

    def test_same_start_and_end_date_allowed(self) -> None:
        record = WeatherCreate(**_valid_create(end_date=TODAY.isoformat()))
        assert record.start_date == record.end_date


# ---------------------------------------------------------------------------
# WeatherCreate — location normalisation
# ---------------------------------------------------------------------------
class TestWeatherCreateLocationNormalisation:
    def test_leading_trailing_whitespace_stripped(self) -> None:
        record = WeatherCreate(**_valid_create(location="  Casablanca  "))
        assert record.location == "Casablanca"

    def test_internal_whitespace_collapsed(self) -> None:
        record = WeatherCreate(**_valid_create(location="New   York"))
        assert record.location == "New York"

    def test_tabs_and_newlines_collapsed(self) -> None:
        record = WeatherCreate(**_valid_create(location="Los\t\nAngeles"))
        assert record.location == "Los Angeles"


# ---------------------------------------------------------------------------
# WeatherCreate — rejection cases
# ---------------------------------------------------------------------------
class TestWeatherCreateRejections:
    def test_empty_location_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            WeatherCreate(**_valid_create(location=""))
        errors = exc_info.value.errors()
        assert any("location" in str(e["loc"]) for e in errors)

    def test_whitespace_only_location_rejected(self) -> None:
        with pytest.raises(ValidationError):
            WeatherCreate(**_valid_create(location="   "))

    def test_single_char_location_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            WeatherCreate(**_valid_create(location="A"))
        errors = exc_info.value.errors()
        assert any("location" in str(e["loc"]) for e in errors)

    def test_end_date_before_start_date_rejected(self) -> None:
        yesterday = (TODAY - timedelta(days=1)).isoformat()
        with pytest.raises(ValidationError, match="end_date must be on or after start_date"):
            WeatherCreate(**_valid_create(end_date=yesterday))

    def test_location_id_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            WeatherCreate(**_valid_create(location_id=0))

    def test_location_id_negative_rejected(self) -> None:
        with pytest.raises(ValidationError):
            WeatherCreate(**_valid_create(location_id=-1))


# ---------------------------------------------------------------------------
# WeatherPatch — valid cases
# ---------------------------------------------------------------------------
class TestWeatherPatchValid:
    def test_location_only(self) -> None:
        patch = WeatherPatch(location="Rabat")
        assert patch.location == "Rabat"
        assert patch.start_date is None

    def test_date_range_only(self) -> None:
        patch = WeatherPatch(start_date=TODAY, end_date=TOMORROW)
        assert patch.start_date == TODAY
        assert patch.end_date == TOMORROW

    def test_location_with_location_id(self) -> None:
        patch = WeatherPatch(location="Rabat", location_id=42)
        assert patch.location == "Rabat"
        assert patch.location_id == 42


# ---------------------------------------------------------------------------
# WeatherPatch — rejection cases
# ---------------------------------------------------------------------------
class TestWeatherPatchRejections:
    def test_empty_body_rejected(self) -> None:
        with pytest.raises(ValidationError, match="at least one of"):
            WeatherPatch()

    def test_location_id_without_location_rejected(self) -> None:
        with pytest.raises(ValidationError, match="location is required"):
            WeatherPatch(location_id=42)


# ---------------------------------------------------------------------------
# ExportFormat enum
# ---------------------------------------------------------------------------
class TestExportFormat:
    def test_json_value(self) -> None:
        assert ExportFormat("json") is ExportFormat.json

    def test_csv_value(self) -> None:
        assert ExportFormat("csv") is ExportFormat.csv

    def test_invalid_format_raises(self) -> None:
        with pytest.raises(ValueError):
            ExportFormat("xml")


# ---------------------------------------------------------------------------
# OutingDayAssessment — score boundary enforcement
# ---------------------------------------------------------------------------
class TestOutingDayAssessmentScore:
    def _make_assessment(self, score: int) -> OutingDayAssessment:
        return OutingDayAssessment(
            weather_date=TODAY,
            score=score,
            weather_description="Mainly clear",
            apparent_temperature_mean_c=24.0,
            precipitation_sum_mm=0.0,
            precipitation_probability_max_pct=5.0,
            wind_speed_max_kmh=12.0,
            penalties=OutingScoreBreakdown(
                precipitation=0,
                weather_condition=0,
                temperature_comfort=0,
                wind=0,
                missing_data=0,
            ),
            reasons=[],
        )

    def test_score_zero_allowed(self) -> None:
        assessment = self._make_assessment(0)
        assert assessment.score == 0

    def test_score_100_allowed(self) -> None:
        assessment = self._make_assessment(100)
        assert assessment.score == 100

    def test_score_negative_rejected(self) -> None:
        with pytest.raises(ValidationError):
            self._make_assessment(-1)

    def test_score_above_100_rejected(self) -> None:
        with pytest.raises(ValidationError):
            self._make_assessment(101)
