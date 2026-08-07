from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "PMA Weather Records API"
    database_url: str = "sqlite:///./weather.db"
    open_meteo_geocoding_url: str = "https://geocoding-api.open-meteo.com/v1/search"
    open_meteo_geocoding_get_url: str = "https://geocoding-api.open-meteo.com/v1/get"
    open_meteo_forecast_url: str = "https://api.open-meteo.com/v1/forecast"
    wikimedia_api_url: str = "https://en.wikipedia.org/w/api.php"
    external_api_timeout_seconds: float = 10.0
    max_date_range_days: int = 16
    weather_past_days: int = 92
    weather_future_days: int = 15
    wikimedia_user_agent: str = (
        "PMA-Weather-Assessment/1.0 (educational project by Rida Boubakr)"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
