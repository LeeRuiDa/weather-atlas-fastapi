"""Unit tests for application configuration and settings.

Validates default configuration values, environment variable overrides,
type coercion, and lru_cache singleton behavior for get_settings().
"""

import pytest

from app.config import Settings, get_settings


class TestSettingsDefaults:
    def test_default_values(self) -> None:
        settings = Settings(_env_file=None)
        assert settings.app_name == "PMA Weather Records API"
        assert settings.database_url == "sqlite:///./weather.db"
        assert "open-meteo.com" in settings.open_meteo_forecast_url
        assert "wikipedia.org" in settings.wikimedia_api_url
        assert settings.external_api_timeout_seconds == 10.0
        assert settings.max_date_range_days == 16
        assert settings.weather_past_days == 92
        assert settings.weather_future_days == 15
        assert "Rida Boubakr" in settings.wikimedia_user_agent

    def test_explicit_kwargs_override_defaults(self) -> None:
        settings = Settings(
            _env_file=None,
            database_url="sqlite:///./custom.db",
            external_api_timeout_seconds=5.0,
            max_date_range_days=7,
        )
        assert settings.database_url == "sqlite:///./custom.db"
        assert settings.external_api_timeout_seconds == 5.0
        assert settings.max_date_range_days == 7


class TestSettingsEnvironmentOverrides:
    def test_database_url_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "sqlite:///./from_env.db")
        settings = Settings(_env_file=None)
        assert settings.database_url == "sqlite:///./from_env.db"

    def test_timeout_env_override_parses_float(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EXTERNAL_API_TIMEOUT_SECONDS", "25.5")
        settings = Settings(_env_file=None)
        assert settings.external_api_timeout_seconds == 25.5

    def test_date_limits_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAX_DATE_RANGE_DAYS", "30")
        monkeypatch.setenv("WEATHER_PAST_DAYS", "180")
        monkeypatch.setenv("WEATHER_FUTURE_DAYS", "30")
        settings = Settings(_env_file=None)
        assert settings.max_date_range_days == 30
        assert settings.weather_past_days == 180
        assert settings.weather_future_days == 30


class TestGetSettingsCaching:
    def test_get_settings_returns_cached_instance(self) -> None:
        get_settings.cache_clear()
        first = get_settings()
        second = get_settings()
        assert first is second

    def test_cache_clear_creates_new_instance(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        get_settings.cache_clear()
        first = get_settings()
        get_settings.cache_clear()
        monkeypatch.setenv("APP_NAME", "Modified App Name")
        second = get_settings()
        assert second.app_name == "Modified App Name"
        assert first is not second
        get_settings.cache_clear()
