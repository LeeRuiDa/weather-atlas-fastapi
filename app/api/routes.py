import csv
import io
import json
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import TypeAdapter
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_open_meteo_client, get_wikimedia_client
from app.schemas import (
    ExportFormat,
    ErrorEnvelope,
    LocationCandidateResponse,
    LocationSearchResponse,
    NearbyResponse,
    OutingPlanResponse,
    WeatherCreate,
    WeatherListResponse,
    WeatherPatch,
    WeatherRecordResponse,
)
from app.services.open_meteo import OpenMeteoClient
from app.services.outing_planner import build_outing_plan
from app.services.records import WeatherRecordService
from app.services.wikimedia import WikimediaClient


router = APIRouter()

UPSTREAM_RESPONSES = {
    502: {"model": ErrorEnvelope, "description": "External provider failure or malformed data."},
    504: {"model": ErrorEnvelope, "description": "External provider timeout."},
}
NOT_FOUND_RESPONSE = {
    404: {"model": ErrorEnvelope, "description": "Weather record does not exist."}
}


@router.get("/", tags=["meta"], summary="Identify the assessment project")
def root() -> dict[str, str]:
    return {
        "project": "PMA Weather Records API",
        "assessment": "PM Accelerator AI Engineer Technical Assessment — Backend Tech Assessment #2",
        "candidate": "Rida Boubakr",
        "docs": "/docs",
        "dashboard": "/dashboard",
        "about": "/about",
    }


@router.get("/health", tags=["meta"], summary="Check service health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/about", tags=["meta"], summary="Show candidate and PM Accelerator information")
def about() -> dict[str, str]:
    return {
        "candidate": "Rida Boubakr",
        "assessment": "PM Accelerator AI Engineer Technical Assessment — Backend Tech Assessment #2",
        "pm_accelerator": (
            "Product Manager Accelerator supports product-management professionals across "
            "career stages, from entry-level candidates to product leaders, through learning "
            "and career-development programs."
        ),
        "pm_accelerator_linkedin": "https://www.linkedin.com/school/pmaccelerator/",
        "source_note": "Description summarized from the Product Manager Accelerator LinkedIn page referenced by the assessment.",
    }


weather_router = APIRouter(prefix="/weather", tags=["weather"])

DbDependency = Annotated[Session, Depends(get_db)]
WeatherClientDependency = Annotated[OpenMeteoClient, Depends(get_open_meteo_client)]
WikimediaClientDependency = Annotated[WikimediaClient, Depends(get_wikimedia_client)]


@router.get(
    "/locations/search",
    response_model=LocationSearchResponse,
    tags=["locations"],
    summary="Search location candidates",
    description=(
        "Returns up to five provider-ranked matches with region, country, coordinates, "
        "timezone, and an ID that can be supplied to CREATE or UPDATE."
    ),
    responses={
        422: {"model": ErrorEnvelope, "description": "Invalid search query."},
        **UPSTREAM_RESPONSES,
    },
)
async def search_location_candidates(
    weather_client: WeatherClientDependency,
    query: str = Query(min_length=2, max_length=200, examples=["Springfield"]),
) -> LocationSearchResponse:
    normalized = " ".join(query.split())
    candidates = await weather_client.search_locations(normalized)
    return LocationSearchResponse(
        query=normalized,
        candidates=[
            LocationCandidateResponse(
                location_id=candidate.location_id,
                name=candidate.name,
                canonical_location=candidate.canonical,
                country=candidate.country,
                country_code=candidate.country_code,
                admin1=candidate.admin1,
                latitude=candidate.latitude,
                longitude=candidate.longitude,
                timezone=candidate.timezone,
            )
            for candidate in candidates
            if candidate.location_id is not None
        ],
    )


@weather_router.post(
    "",
    response_model=WeatherRecordResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create and persist a weather snapshot",
    description=(
        "Validates the request, resolves the location, retrieves real daily weather, "
        "and stores the request and complete snapshot in SQLite."
    ),
    responses={
        422: {"model": ErrorEnvelope, "description": "Invalid location or date range."},
        **UPSTREAM_RESPONSES,
    },
)
async def create_weather_record(
    payload: WeatherCreate,
    db: DbDependency,
    weather_client: WeatherClientDependency,
) -> WeatherRecordResponse:
    record = await WeatherRecordService(db, weather_client).create(payload)
    return WeatherRecordResponse.model_validate(record)


@weather_router.get(
    "",
    response_model=WeatherListResponse,
    summary="List persisted weather records",
    description="Reads saved snapshots from SQLite without calling the weather provider again.",
)
def list_weather_records(
    db: DbDependency,
    weather_client: WeatherClientDependency,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> WeatherListResponse:
    records, total = WeatherRecordService(db, weather_client).list_records(offset, limit)
    return WeatherListResponse(
        items=[WeatherRecordResponse.model_validate(record) for record in records],
        total=total,
        offset=offset,
        limit=limit,
    )


@weather_router.get(
    "/export",
    summary="Export the weather database",
    description="Downloads all stored records as nested JSON or one CSV row per weather day.",
)
def export_weather_records(
    db: DbDependency,
    weather_client: WeatherClientDependency,
    format: ExportFormat = Query(default=ExportFormat.json),
) -> Response:
    records = WeatherRecordService(db, weather_client).all_records()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    if format is ExportFormat.json:
        adapter = TypeAdapter(list[WeatherRecordResponse])
        payload = adapter.dump_python(records, mode="json")
        return Response(
            content=json.dumps(payload, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="weather-export-{timestamp}.json"'
            },
        )

    output = io.StringIO(newline="")
    fieldnames = [
        "record_id",
        "original_location",
        "canonical_location",
        "country_code",
        "latitude",
        "longitude",
        "timezone",
        "start_date",
        "end_date",
        "retrieved_at",
        "weather_date",
        "temperature_mean_c",
        "temperature_min_c",
        "temperature_max_c",
        "apparent_temperature_mean_c",
        "precipitation_sum_mm",
        "precipitation_probability_max_pct",
        "humidity_mean_pct",
        "wind_speed_max_kmh",
        "weather_code",
        "weather_description",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for record in records:
        for day in record.days:
            writer.writerow(
                {
                    "record_id": record.id,
                    "original_location": record.original_location,
                    "canonical_location": record.canonical_location,
                    "country_code": record.country_code,
                    "latitude": record.latitude,
                    "longitude": record.longitude,
                    "timezone": record.timezone,
                    "start_date": record.start_date.isoformat(),
                    "end_date": record.end_date.isoformat(),
                    "retrieved_at": record.retrieved_at.isoformat(),
                    "weather_date": day.weather_date.isoformat(),
                    "temperature_mean_c": day.temperature_mean_c,
                    "temperature_min_c": day.temperature_min_c,
                    "temperature_max_c": day.temperature_max_c,
                    "apparent_temperature_mean_c": day.apparent_temperature_mean_c,
                    "precipitation_sum_mm": day.precipitation_sum_mm,
                    "precipitation_probability_max_pct": day.precipitation_probability_max_pct,
                    "humidity_mean_pct": day.humidity_mean_pct,
                    "wind_speed_max_kmh": day.wind_speed_max_kmh,
                    "weather_code": day.weather_code,
                    "weather_description": day.weather_description,
                }
            )
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="weather-export-{timestamp}.csv"'
        },
    )


@weather_router.get(
    "/{record_id}",
    response_model=WeatherRecordResponse,
    summary="Read one persisted weather record",
    responses=NOT_FOUND_RESPONSE,
)
def get_weather_record(
    record_id: int,
    db: DbDependency,
    weather_client: WeatherClientDependency,
) -> WeatherRecordResponse:
    record = WeatherRecordService(db, weather_client).get(record_id)
    return WeatherRecordResponse.model_validate(record)


@weather_router.patch(
    "/{record_id}",
    response_model=WeatherRecordResponse,
    summary="Update and atomically refresh a weather record",
    description=(
        "Allows request-controlled fields to change, then re-resolves/refetches weather so "
        "trusted provider data cannot become inconsistent."
    ),
    responses={
        **NOT_FOUND_RESPONSE,
        422: {"model": ErrorEnvelope, "description": "Invalid update or date range."},
        **UPSTREAM_RESPONSES,
    },
)
async def update_weather_record(
    record_id: int,
    payload: WeatherPatch,
    db: DbDependency,
    weather_client: WeatherClientDependency,
) -> WeatherRecordResponse:
    record = await WeatherRecordService(db, weather_client).update(record_id, payload)
    return WeatherRecordResponse.model_validate(record)


@weather_router.delete(
    "/{record_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a persisted weather record",
    responses=NOT_FOUND_RESPONSE,
)
def delete_weather_record(
    record_id: int,
    db: DbDependency,
    weather_client: WeatherClientDependency,
) -> Response:
    WeatherRecordService(db, weather_client).delete(record_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@weather_router.get(
    "/{record_id}/nearby",
    response_model=NearbyResponse,
    summary="Find nearby notable places",
    description="Uses stored coordinates with Wikimedia geosearch; it does not refetch weather.",
    responses={**NOT_FOUND_RESPONSE, **UPSTREAM_RESPONSES},
)
async def nearby_places(
    record_id: int,
    db: DbDependency,
    weather_client: WeatherClientDependency,
    wikimedia_client: WikimediaClientDependency,
    radius_m: int = Query(default=10_000, ge=10, le=10_000),
    limit: int = Query(default=5, ge=1, le=20),
) -> NearbyResponse:
    record = WeatherRecordService(db, weather_client).get(record_id)
    places = await wikimedia_client.nearby_places(
        record.latitude, record.longitude, radius_m, limit
    )
    return NearbyResponse(
        weather_record_id=record.id,
        canonical_location=record.canonical_location,
        radius_m=radius_m,
        places=places,
    )


@weather_router.get(
    "/{record_id}/outing-plan",
    response_model=OutingPlanResponse,
    summary="Build a weather-aware outing plan",
    description=(
        "Deterministically scores each stored weather day, explains every penalty, selects "
        "the best day, and combines it with nearby Wikimedia places. This is not AI/ML."
    ),
    responses={**NOT_FOUND_RESPONSE, **UPSTREAM_RESPONSES},
)
async def build_weather_outing_plan(
    record_id: int,
    db: DbDependency,
    weather_client: WeatherClientDependency,
    wikimedia_client: WikimediaClientDependency,
    radius_m: int = Query(default=10_000, ge=10, le=10_000),
    limit: int = Query(default=5, ge=1, le=20),
) -> OutingPlanResponse:
    record = WeatherRecordService(db, weather_client).get(record_id)
    places = await wikimedia_client.nearby_places(
        record.latitude, record.longitude, radius_m, limit
    )
    return build_outing_plan(record, places, radius_m)


router.include_router(weather_router)
