from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.errors import DateRangeNotSupportedError, RecordNotFoundError
from app.models import WeatherDay, WeatherRecord
from app.schemas import WeatherCreate, WeatherPatch
from app.services.open_meteo import GeocodedLocation, OpenMeteoClient, WeatherSnapshot


class WeatherRecordService:
    def __init__(self, db: Session, weather_client: OpenMeteoClient) -> None:
        self.db = db
        self.weather_client = weather_client

    async def create(self, payload: WeatherCreate) -> WeatherRecord:
        self.weather_client.validate_date_range(payload.start_date, payload.end_date)
        if payload.location_id is not None:
            location = await self.weather_client.resolve_location_id(
                payload.location_id, payload.location
            )
        else:
            location = await self.weather_client.resolve_location(payload.location)
        snapshot = await self.weather_client.fetch_weather(
            location, payload.start_date, payload.end_date
        )
        record = self._build_record(location, snapshot, payload.start_date, payload.end_date)
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return self.get(record.id)

    def list_records(self, offset: int, limit: int) -> tuple[list[WeatherRecord], int]:
        statement = (
            select(WeatherRecord)
            .options(selectinload(WeatherRecord.days))
            .order_by(WeatherRecord.id.desc())
            .offset(offset)
            .limit(limit)
        )
        records = list(self.db.scalars(statement).all())
        total = self.db.scalar(select(func.count(WeatherRecord.id))) or 0
        return records, total

    def all_records(self) -> list[WeatherRecord]:
        statement = (
            select(WeatherRecord)
            .options(selectinload(WeatherRecord.days))
            .order_by(WeatherRecord.id)
        )
        return list(self.db.scalars(statement).all())

    def get(self, record_id: int) -> WeatherRecord:
        statement = (
            select(WeatherRecord)
            .where(WeatherRecord.id == record_id)
            .options(selectinload(WeatherRecord.days))
        )
        record = self.db.scalar(statement)
        if record is None:
            raise RecordNotFoundError(record_id)
        return record

    async def update(self, record_id: int, payload: WeatherPatch) -> WeatherRecord:
        record = self.get(record_id)
        start_date = payload.start_date or record.start_date
        end_date = payload.end_date or record.end_date
        if end_date < start_date:
            raise DateRangeNotSupportedError(
                "end_date must be on or after start_date.",
                {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
            )
        self.weather_client.validate_date_range(start_date, end_date)

        if payload.location_id is not None and payload.location is not None:
            location = await self.weather_client.resolve_location_id(
                payload.location_id, payload.location
            )
        elif payload.location is not None:
            location = await self.weather_client.resolve_location(payload.location)
        else:
            location = GeocodedLocation(
                original=record.original_location,
                canonical=record.canonical_location,
                latitude=record.latitude,
                longitude=record.longitude,
                timezone=record.timezone,
                country_code=record.country_code,
                admin1=record.admin1,
                match_type=record.location_match,
            )
        snapshot = await self.weather_client.fetch_weather(location, start_date, end_date)

        record.original_location = location.original
        record.canonical_location = location.canonical
        record.country_code = location.country_code
        record.admin1 = location.admin1
        record.latitude = location.latitude
        record.longitude = location.longitude
        record.timezone = snapshot.timezone
        record.location_match = location.match_type
        record.start_date = start_date
        record.end_date = end_date
        record.retrieved_at = snapshot.retrieved_at
        record.days.clear()
        self.db.flush()
        record.days.extend(self._build_days(snapshot))
        self.db.commit()
        return self.get(record_id)

    def delete(self, record_id: int) -> None:
        record = self.get(record_id)
        self.db.delete(record)
        self.db.commit()

    def _build_record(
        self,
        location: GeocodedLocation,
        snapshot: WeatherSnapshot,
        start_date: date,
        end_date: date,
    ) -> WeatherRecord:
        return WeatherRecord(
            original_location=location.original,
            canonical_location=location.canonical,
            country_code=location.country_code,
            admin1=location.admin1,
            latitude=location.latitude,
            longitude=location.longitude,
            timezone=snapshot.timezone,
            location_match=location.match_type,
            start_date=start_date,
            end_date=end_date,
            retrieved_at=snapshot.retrieved_at,
            days=self._build_days(snapshot),
        )

    def _build_days(self, snapshot: WeatherSnapshot) -> list[WeatherDay]:
        return [
            WeatherDay(
                weather_date=day.weather_date,
                temperature_mean_c=day.temperature_mean_c,
                temperature_min_c=day.temperature_min_c,
                temperature_max_c=day.temperature_max_c,
                apparent_temperature_mean_c=day.apparent_temperature_mean_c,
                precipitation_sum_mm=day.precipitation_sum_mm,
                precipitation_probability_max_pct=day.precipitation_probability_max_pct,
                humidity_mean_pct=day.humidity_mean_pct,
                wind_speed_max_kmh=day.wind_speed_max_kmh,
                weather_code=day.weather_code,
                weather_description=day.weather_description,
            )
            for day in snapshot.days
        ]
