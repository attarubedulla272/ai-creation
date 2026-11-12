"""FastAPI application factory.

Run the API from the backend directory with:
    uvicorn app.main:app --reload --port 8000
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.router import api_router
from app.core.config import Settings
from app.core.errors import APIError
from app.db.session import create_session_factory
from app.services.content_processing import run_content_worker
from app.services.content_providers import create_scene_generation_provider
from app.services.media_processing import run_media_worker
from app.services.smart_clipper import run_smart_clipper_worker
from app.services.storage import LocalStorage
from app.services.timeline_export import run_timeline_export_worker
from app.services.voice_processing import run_voice_worker
from app.services.voice_providers import create_default_voice_providers
from app.services.youtube_api import YouTubeApiClient, YouTubeOAuthNotConfigured
from app.services.youtube_publishing import run_youtube_upload_worker

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the API application with the supplied or environment-backed settings."""

    app_settings = settings or Settings()
    engine, session_factory = create_session_factory(app_settings)
    storage = LocalStorage(app_settings.storage_path)
    voice_providers = create_default_voice_providers(app_settings)
    scene_generation_provider = create_scene_generation_provider(app_settings)
    try:
        youtube_client: YouTubeApiClient | None = YouTubeApiClient(app_settings)
    except YouTubeOAuthNotConfigured:
        youtube_client = None

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        worker_tasks = []
        if session_factory is not None:
            worker_tasks = [
                asyncio.create_task(run_media_worker(session_factory, storage)),
                asyncio.create_task(run_timeline_export_worker(session_factory, storage)),
                asyncio.create_task(run_voice_worker(session_factory, storage, voice_providers)),
                asyncio.create_task(
                    run_smart_clipper_worker(session_factory, storage, voice_providers)
                ),
                asyncio.create_task(
                    run_content_worker(
                        session_factory,
                        lambda: application.state.scene_generation_provider,
                        storage,
                        app_settings,
                    )
                ),
            ]
            if application.state.youtube_client is not None:
                worker_tasks.append(
                    asyncio.create_task(
                        run_youtube_upload_worker(
                            session_factory,
                            storage,
                            application.state.youtube_client,
                        )
                    )
                )
        try:
            yield
        finally:
            for worker_task in worker_tasks:
                worker_task.cancel()
            for worker_task in worker_tasks:
                try:
                    await worker_task
                except asyncio.CancelledError:
                    pass
            if engine is not None:
                await engine.dispose()

    application = FastAPI(
        title=app_settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )
    application.state.settings = app_settings
    application.state.engine = engine
    application.state.session_factory = session_factory
    application.state.storage = storage
    application.state.voice_providers = voice_providers
    application.state.scene_generation_provider = scene_generation_provider
    application.state.youtube_client = youtube_client

    if app_settings.cors_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=app_settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type"],
        )

    @application.middleware("http")
    async def add_request_id(request: Request, call_next):
        request_id = str(uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @application.exception_handler(APIError)
    async def handle_api_error(request: Request, error: APIError) -> JSONResponse:
        error_body: dict[str, object] = {
            "code": error.code,
            "message": error.message,
            "request_id": request.state.request_id,
        }
        if error.details is not None:
            error_body["details"] = error.details
        return JSONResponse(
            status_code=error.status_code,
            content={"error": error_body},
        )

    @application.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, error: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            headers=error.headers,
            content={
                "error": {
                    "code": "http_error",
                    "message": str(error.detail),
                    "request_id": request.state.request_id,
                }
            },
        )

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        details = [
            {
                "location": list(item["loc"]),
                "message": item["msg"],
                "type": item["type"],
            }
            for item in error.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Request validation failed.",
                    "details": details,
                    "request_id": request.state.request_id,
                }
            },
        )

    @application.exception_handler(SQLAlchemyError)
    async def handle_database_error(request: Request, error: SQLAlchemyError) -> JSONResponse:
        logger.exception("Database request failed", extra={"request_id": request.state.request_id})
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "database_unavailable",
                    "message": "The database request could not be completed.",
                    "request_id": request.state.request_id,
                }
            },
        )

    @application.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, error: Exception) -> JSONResponse:
        logger.error(
            "Unhandled API request error",
            exc_info=error,
            extra={"request_id": request.state.request_id},
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "An unexpected error occurred.",
                    "request_id": request.state.request_id,
                }
            },
        )

    @application.get("/health", tags=["system"], include_in_schema=True)
    async def root_health() -> dict[str, str]:
        return {"status": "ok"}

    application.include_router(api_router, prefix=app_settings.api_v1_prefix)
    return application


app = create_app()
