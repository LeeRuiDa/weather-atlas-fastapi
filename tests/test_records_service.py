"""Unit tests for WeatherRecordService.

Tests direct database interactions, record building, cascade deletes,
pagination, and update logic in isolation from HTTP routing.
"""

from collections.abc import Generator
from datetime import date, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import Base, build_engine, build_session_factory
from app.errors import DateRangeNotSupportedError, RecordNotFoundError
from app.models import WeatherDay, WeatherRecord
from app.schemas import WeatherCreate, WeatherPatch
from app.services.records import WeatherRecordService
from tests.conftest import FakeOpenMeteoClient


TODAY = date.today()
TOMORROW = TODAY + timedelta(days=1)
DAY_AFTER = TODAY + timedelta(days=2)


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine = build_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = build_session_factory(engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture
def service(db_session: Session) -> WeatherRecordService:
    weather_client = FakeOpenMeteoClient()
    return WeatherRecordService(db=db_session, weather_client=weather_client)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Create tests
# ---------------------------------------------------------------------------
class TestWeatherRecordServiceCreate:
    @pytest.mark.asyncio
    async def test_create_persists_record_and_days(
        self, service: WeatherRecordService, db_session: Session
    ) -> None:
        payload = WeatherCreate(
            location="Casablanca",
            start_date=TODAY,
            end_date=TOMORROW,
        )
        record = await service.create(payload)

        assert record.id is not None
        assert record.original_location == "Casablanca"
        assert record.canonical_location == "Casablanca, Casablanca-Settat, Morocco"
        assert record.start_date == TODAY
        assert record.end_date == TOMORROW
        assert len(record.days) == 2
        assert record.days[0].weather_date == TODAY
        assert record.days[1].weather_date == TOMORROW

        persisted = db_session.get(WeatherRecord, record.id)
        assert persisted is not None
        assert len(persisted.days) == 2

    @pytest.mark.asyncio
    async def test_create_with_location_id_uses_selected_candidate(
        self, service: WeatherRecordService
    ) -> None:
        payload = WeatherCreate(
            location="Casablanca",
            location_id=222,
            start_date=TODAY,
            end_date=TODAY,
        )
        record = await service.create(payload)

        assert record.location_match == "selected"
        assert record.canonical_location == "Casablanca, Centre-Val de Loire, France"
        assert record.country_code == "FR"


# ---------------------------------------------------------------------------
# Read and List tests
# ---------------------------------------------------------------------------
class TestWeatherRecordServiceReadAndList:
    @pytest.mark.asyncio
    async def test_get_existing_record(self, service: WeatherRecordService) -> None:
        payload = WeatherCreate(
            location="Rabat",
            start_date=TODAY,
            end_date=TODAY,
        )
        created = await service.create(payload)
        fetched = service.get(created.id)

        assert fetched.id == created.id
        assert fetched.canonical_location == created.canonical_location
        assert len(fetched.days) == 1

    def test_get_non_existent_record_raises(self, service: WeatherRecordService) -> None:
        with pytest.raises(RecordNotFoundError) as exc_info:
            service.get(99999)
        assert exc_info.value.status_code == 404
        assert "99999" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_list_records_pagination(self, service: WeatherRecordService) -> None:
        for loc in ["Casablanca", "Rabat", "Tangier"]:
            await service.create(
                WeatherCreate(location=loc, start_date=TODAY, end_date=TODAY)
            )

        records_page1, total = service.list_records(offset=0, limit=2)
        assert total == 3
        assert len(records_page1) == 2

        records_page2, total = service.list_records(offset=2, limit=2)
        assert total == 3
        assert len(records_page2) == 1

    @pytest.mark.asyncio
    async def test_all_records_ordering(self, service: WeatherRecordService) -> None:
        r1 = await service.create(
            WeatherCreate(location="Casablanca", start_date=TODAY, end_date=TODAY)
        )
        r2 = await service.create(
            WeatherCreate(location="Rabat", start_date=TODAY, end_date=TODAY)
        )

        all_recs = service.all_records()
        assert len(all_recs) == 2
        assert all_recs[0].id == r1.id
        assert all_recs[1].id == r2.id


# ---------------------------------------------------------------------------
# Update tests
# ---------------------------------------------------------------------------
class TestWeatherRecordServiceUpdate:
    @pytest.mark.asyncio
    async def test_update_location_and_dates_replaces_days(
        self, service: WeatherRecordService
    ) -> None:
        created = await service.create(
            WeatherCreate(location="Casablanca", start_date=TODAY, end_date=TODAY)
        )
        assert len(created.days) == 1

        patch = WeatherPatch(
            location="Rabat",
            start_date=TODAY,
            end_date=DAY_AFTER,
        )
        updated = await service.update(created.id, patch)

        assert updated.id == created.id
        assert updated.original_location == "Rabat"
        assert "Rabat" in updated.canonical_location
        assert updated.start_date == TODAY
        assert updated.end_date == DAY_AFTER
        assert len(updated.days) == 3

    @pytest.mark.asyncio
    async def test_update_with_location_id(self, service: WeatherRecordService) -> None:
        created = await service.create(
            WeatherCreate(location="Casablanca", start_date=TODAY, end_date=TODAY)
        )
        patch = WeatherPatch(location="Casablanca", location_id=222)
        updated = await service.update(created.id, patch)

        assert updated.location_match == "selected"
        assert "France" in updated.canonical_location

    @pytest.mark.asyncio
    async def test_update_invalid_date_range_raises(
        self, service: WeatherRecordService
    ) -> None:
        created = await service.create(
            WeatherCreate(location="Casablanca", start_date=TODAY, end_date=TOMORROW)
        )
        yesterday = TODAY - timedelta(days=1)
        patch = WeatherPatch(end_date=yesterday)

        with pytest.raises(DateRangeNotSupportedError):
            await service.update(created.id, patch)


# ---------------------------------------------------------------------------
# Delete tests
# ---------------------------------------------------------------------------
class TestWeatherRecordServiceDelete:
    @pytest.mark.asyncio
    async def test_delete_cascades_to_days(
        self, service: WeatherRecordService, db_session: Session
    ) -> None:
        created = await service.create(
            WeatherCreate(location="Casablanca", start_date=TODAY, end_date=TOMORROW)
        )
        record_id = created.id

        days_before = list(
            db_session.scalars(
                select(WeatherDay).where(WeatherDay.weather_record_id == record_id)
            ).all()
        )
        assert len(days_before) == 2

        service.delete(record_id)

        with pytest.raises(RecordNotFoundError):
            service.get(record_id)

        days_after = list(
            db_session.scalars(
                select(WeatherDay).where(WeatherDay.weather_record_id == record_id)
            ).all()
        )
        assert len(days_after) == 0

    def test_delete_non_existent_record_raises(
        self, service: WeatherRecordService
    ) -> None:
        with pytest.raises(RecordNotFoundError):
            service.delete(99999)
