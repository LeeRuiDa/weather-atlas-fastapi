from app.errors import NoWeatherDataError
from app.models import WeatherDay, WeatherRecord
from app.schemas import (
    NearbyPlaceResponse,
    OutingDayAssessment,
    OutingPlanResponse,
    OutingScoreBreakdown,
)


METHODOLOGY = (
    "Scores start at 100. Deterministic penalties are applied for rain amount and "
    "probability, WMO weather severity, apparent temperature outside 16–30°C, wind "
    "above 20 km/h, and missing measurements. Highest score wins; ties favor the "
    "earlier date."
)


WEATHER_PENALTIES = {
    0: 0,
    1: 1,
    2: 3,
    3: 6,
    45: 10,
    48: 12,
    51: 7,
    53: 9,
    55: 12,
    56: 15,
    57: 18,
    61: 10,
    63: 16,
    65: 24,
    66: 23,
    67: 28,
    71: 12,
    73: 18,
    75: 25,
    77: 15,
    80: 12,
    81: 18,
    82: 28,
    85: 18,
    86: 26,
    95: 30,
    96: 35,
    99: 40,
}


def assess_day(day: WeatherDay) -> OutingDayAssessment:
    missing_penalty = 0.0

    if day.precipitation_sum_mm is None:
        amount_penalty = 0.0
        missing_penalty += 2.0
    else:
        amount_penalty = min(20.0, max(0.0, day.precipitation_sum_mm) * 4.0)

    if day.precipitation_probability_max_pct is None:
        probability_penalty = 0.0
        missing_penalty += 2.0
    else:
        probability_penalty = min(
            20.0, max(0.0, day.precipitation_probability_max_pct) * 0.2
        )
    precipitation_penalty = amount_penalty + probability_penalty

    if day.weather_code is None:
        weather_penalty = 0.0
        missing_penalty += 8.0
    else:
        weather_penalty = float(WEATHER_PENALTIES.get(day.weather_code, 8))

    apparent_temperature = (
        day.apparent_temperature_mean_c
        if day.apparent_temperature_mean_c is not None
        else day.temperature_mean_c
    )
    if apparent_temperature is None:
        temperature_penalty = 0.0
        missing_penalty += 8.0
    elif apparent_temperature < 16.0:
        temperature_penalty = min(20.0, (16.0 - apparent_temperature) * 2.5)
    elif apparent_temperature > 30.0:
        temperature_penalty = min(20.0, (apparent_temperature - 30.0) * 2.5)
    else:
        temperature_penalty = 0.0

    if day.wind_speed_max_kmh is None:
        wind_penalty = 0.0
        missing_penalty += 5.0
    else:
        wind_penalty = min(20.0, max(0.0, day.wind_speed_max_kmh - 20.0) * 0.8)

    penalties = OutingScoreBreakdown(
        precipitation=round(precipitation_penalty, 1),
        weather_condition=round(weather_penalty, 1),
        temperature_comfort=round(temperature_penalty, 1),
        wind=round(wind_penalty, 1),
        missing_data=round(missing_penalty, 1),
    )
    total_penalty = sum(
        (
            penalties.precipitation,
            penalties.weather_condition,
            penalties.temperature_comfort,
            penalties.wind,
            penalties.missing_data,
        )
    )
    score = max(0, min(100, round(100 - total_penalty)))

    reasons = [f"{day.weather_description} is forecast."]
    if (
        day.precipitation_sum_mm is not None
        and day.precipitation_probability_max_pct is not None
    ):
        if (
            day.precipitation_sum_mm <= 0.5
            and day.precipitation_probability_max_pct <= 20
        ):
            reasons.append("Little rain is expected.")
        else:
            reasons.append(
                f"Rain risk is {day.precipitation_probability_max_pct:.0f}% with "
                f"{day.precipitation_sum_mm:.1f} mm expected."
            )
    if apparent_temperature is not None:
        if 16.0 <= apparent_temperature <= 30.0:
            reasons.append(
                f"Apparent temperature is comfortable at about {apparent_temperature:.1f}°C."
            )
        elif apparent_temperature < 16.0:
            reasons.append(
                f"It may feel cool at about {apparent_temperature:.1f}°C."
            )
        else:
            reasons.append(
                f"It may feel hot at about {apparent_temperature:.1f}°C."
            )
    if day.wind_speed_max_kmh is not None:
        if day.wind_speed_max_kmh <= 20.0:
            reasons.append(f"Winds stay manageable near {day.wind_speed_max_kmh:.0f} km/h.")
        else:
            reasons.append(f"Wind may reach {day.wind_speed_max_kmh:.0f} km/h.")
    if missing_penalty:
        reasons.append("Some measurements are missing, so the score is conservative.")

    return OutingDayAssessment(
        weather_date=day.weather_date,
        score=score,
        weather_description=day.weather_description,
        apparent_temperature_mean_c=apparent_temperature,
        precipitation_sum_mm=day.precipitation_sum_mm,
        precipitation_probability_max_pct=day.precipitation_probability_max_pct,
        wind_speed_max_kmh=day.wind_speed_max_kmh,
        penalties=penalties,
        reasons=reasons,
    )


def build_outing_plan(
    record: WeatherRecord,
    nearby_places: list[NearbyPlaceResponse],
    radius_m: int,
) -> OutingPlanResponse:
    if not record.days:
        raise NoWeatherDataError(record.id)
    daily_scores = [assess_day(day) for day in record.days]
    daily_scores.sort(key=lambda day: day.weather_date)
    best_day = sorted(
        daily_scores, key=lambda day: (-day.score, day.weather_date)
    )[0]
    summary = (
        f"{best_day.weather_date.isoformat()} is the best outing day with a "
        f"{best_day.score}/100 suitability score. "
        + " ".join(best_day.reasons[:3])
    )
    return OutingPlanResponse(
        weather_record_id=record.id,
        canonical_location=record.canonical_location,
        best_day=best_day,
        daily_scores=daily_scores,
        summary=summary,
        methodology=METHODOLOGY,
        radius_m=radius_m,
        nearby_places=nearby_places,
    )

