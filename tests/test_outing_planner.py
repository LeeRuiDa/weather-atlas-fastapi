from datetime import date

from app.models import WeatherDay
from app.services.outing_planner import assess_day


def make_day(
    *,
    weather_code: int,
    description: str,
    precipitation_mm: float,
    precipitation_probability: float,
    apparent_temperature: float,
    wind_kmh: float,
) -> WeatherDay:
    return WeatherDay(
        weather_date=date(2026, 8, 6),
        temperature_mean_c=apparent_temperature,
        apparent_temperature_mean_c=apparent_temperature,
        precipitation_sum_mm=precipitation_mm,
        precipitation_probability_max_pct=precipitation_probability,
        wind_speed_max_kmh=wind_kmh,
        weather_code=weather_code,
        weather_description=description,
    )


def test_clear_comfortable_day_scores_above_stormy_day() -> None:
    clear = assess_day(
        make_day(
            weather_code=1,
            description="Mainly clear",
            precipitation_mm=0.0,
            precipitation_probability=5,
            apparent_temperature=24,
            wind_kmh=12,
        )
    )
    stormy = assess_day(
        make_day(
            weather_code=95,
            description="Thunderstorm",
            precipitation_mm=8,
            precipitation_probability=90,
            apparent_temperature=34,
            wind_kmh=42,
        )
    )
    assert clear.score == 98
    assert stormy.score < 20
    assert clear.score > stormy.score
    assert stormy.penalties.weather_condition == 30


def test_missing_measurements_receive_conservative_penalty() -> None:
    day = WeatherDay(
        weather_date=date(2026, 8, 6),
        weather_description="Unknown",
        weather_code=None,
        apparent_temperature_mean_c=None,
        temperature_mean_c=None,
        precipitation_sum_mm=None,
        precipitation_probability_max_pct=None,
        wind_speed_max_kmh=None,
    )
    assessment = assess_day(day)
    assert assessment.penalties.missing_data == 25
    assert assessment.score == 75
    assert "conservative" in assessment.reasons[-1]
