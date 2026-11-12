"""Version 1 API router."""

from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.clipper import router as clipper_router
from app.api.v1.content import jobs_router as content_jobs_router
from app.api.v1.content import registry_router as content_registry_router
from app.api.v1.content import router as content_router
from app.api.v1.health import router as health_router
from app.api.v1.media import router as media_router
from app.api.v1.projects import router as projects_router
from app.api.v1.publishing import router as publishing_router
from app.api.v1.timeline import export_router as timeline_export_router
from app.api.v1.timeline import router as timeline_router
from app.api.v1.voice import router as voice_router
from app.api.v1.youtube import router as youtube_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(projects_router)
api_router.include_router(media_router)
api_router.include_router(timeline_router)
api_router.include_router(timeline_export_router)
api_router.include_router(voice_router)
api_router.include_router(content_router)
api_router.include_router(content_jobs_router)
api_router.include_router(content_registry_router)
api_router.include_router(clipper_router)
api_router.include_router(publishing_router)
api_router.include_router(youtube_router)
