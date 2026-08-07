from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WeatherRecord(Base):
    __tablename__ = "weather_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    original_location: Mapped[str] = mapped_column(String(200))
    canonical_location: Mapped[str] = mapped_column(String(300))
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    admin1: Mapped[str | None] = mapped_column(String(150), nullable=True)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    timezone: Mapped[str] = mapped_column(String(100))
    location_match: Mapped[str] = mapped_column(String(20))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    days: Mapped[list["WeatherDay"]] = relationship(
        back_populates="record",
        cascade="all, delete-orphan",
        order_by="WeatherDay.weather_date",
    )


class WeatherDay(Base):
    __tablename__ = "weather_days"
    __table_args__ = (
        UniqueConstraint("weather_record_id", "weather_date", name="uq_record_weather_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    weather_record_id: Mapped[int] = mapped_column(
        ForeignKey("weather_records.id", ondelete="CASCADE"), index=True
    )
    weather_date: Mapped[date] = mapped_column(Date)
    temperature_mean_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    temperature_min_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    temperature_max_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    apparent_temperature_mean_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    precipitation_sum_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    precipitation_probability_max_pct: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    humidity_mean_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_speed_max_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    weather_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weather_description: Mapped[str] = mapped_column(String(100))

    record: Mapped[WeatherRecord] = relationship(back_populates="days")

