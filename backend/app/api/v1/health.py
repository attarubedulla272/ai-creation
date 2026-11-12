"""Liveness endpoint for the API process."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class HealthResponse(BaseModel):
    """Minimal response indicating that the API process can serve requests."""

    status: Literal["ok"] = "ok"


@router.get("/health", response_model=HealthResponse, tags=["system"])
def health_check() -> HealthResponse:
    """Return liveness without implying database or worker readiness."""

    return HealthResponse()
