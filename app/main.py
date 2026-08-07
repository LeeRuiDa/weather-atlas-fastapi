from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.config import Settings, get_settings
from app.database import Base, build_engine, build_session_factory
from app.errors import AppError
from app.services.open_meteo import OpenMeteoClient
from app.services.wikimedia import WikimediaClient


OPENAPI_TAGS = [
    {
        "name": "meta",
        "description": "Project identity, candidate information, and service health.",
    },
    {
        "name": "locations",
        "description": "Provider-backed location discovery for deliberate ambiguity handling.",
    },
    {
        "name": "weather",
        "description": (
            "Persistent weather CRUD, traveler context, deterministic outing planning, "
            "and database exports."
        ),
    },
]


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    engine = build_engine(resolved_settings.database_url)
    session_factory = build_session_factory(engine)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        Base.metadata.create_all(engine)
        yield
        engine.dispose()

    application = FastAPI(
        title=resolved_settings.app_name,
        version="1.1.0",
        description=(
            "PM Accelerator AI Engineer Technical Assessment — Backend Tech Assessment #2. "
            "Weather CRUD API by Rida Boubakr, with an optional Weather Explorer at /dashboard."
        ),
        openapi_tags=OPENAPI_TAGS,
        swagger_ui_parameters={"defaultModelsExpandDepth": 1},
        lifespan=lifespan,
    )
    application.state.settings = resolved_settings
    application.state.engine = engine
    application.state.session_factory = session_factory
    application.state.open_meteo_client = OpenMeteoClient(resolved_settings)
    application.state.wikimedia_client = WikimediaClient(resolved_settings)
    application.include_router(router)
    static_directory = Path(__file__).resolve().parent / "static"
    application.mount("/static", StaticFiles(directory=static_directory), name="static")

    @application.get("/dashboard", include_in_schema=False)
    def dashboard() -> FileResponse:
        return FileResponse(static_directory / "dashboard.html")

    @application.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        error: dict[str, Any] = {"code": exc.code, "message": exc.message}
        if exc.details is not None:
            error["details"] = exc.details
        return JSONResponse(status_code=exc.status_code, content={"error": error})

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = [
            {
                "location": list(error["loc"]),
                "message": error["msg"],
                "type": error["type"],
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Request validation failed.",
                    "details": details,
                }
            },
        )

    return application


app = create_app()
