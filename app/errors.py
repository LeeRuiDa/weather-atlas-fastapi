from typing import Any


class AppError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        super().__init__(message)


class RecordNotFoundError(AppError):
    def __init__(self, record_id: int) -> None:
        super().__init__(
            404,
            "weather_record_not_found",
            f"Weather record {record_id} was not found.",
        )


class LocationNotFoundError(AppError):
    def __init__(self, location: str) -> None:
        super().__init__(
            422,
            "location_not_found",
            f"Could not resolve location '{location}'. Try a city, town, or postal code.",
        )


class DateRangeNotSupportedError(AppError):
    def __init__(self, message: str, details: dict[str, Any]) -> None:
        super().__init__(422, "date_range_not_supported", message, details)


class UpstreamTimeoutError(AppError):
    def __init__(self, provider: str) -> None:
        super().__init__(
            504,
            "upstream_timeout",
            f"{provider} did not respond in time. Please try again.",
            {"provider": provider},
        )


class UpstreamServiceError(AppError):
    def __init__(self, provider: str, status_code: int | None = None) -> None:
        details: dict[str, Any] = {"provider": provider}
        if status_code is not None:
            details["upstream_status"] = status_code
        super().__init__(
            502,
            "upstream_service_error",
            f"{provider} is currently unavailable. Please try again.",
            details,
        )


class UpstreamDataError(AppError):
    def __init__(self, provider: str) -> None:
        super().__init__(
            502,
            "upstream_data_error",
            f"{provider} returned an unexpected response.",
            {"provider": provider},
        )


class NoWeatherDataError(AppError):
    def __init__(self, record_id: int) -> None:
        super().__init__(
            409,
            "weather_data_unavailable",
            f"Weather record {record_id} has no daily data to score.",
        )
