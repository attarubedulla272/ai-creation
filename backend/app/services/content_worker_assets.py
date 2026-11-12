"""Short-lived, asset-scoped reference access for the private generation worker."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
from uuid import UUID

import jwt

from app.core.config import Settings


def create_worker_asset_url(
    settings: Settings,
    owner_id: UUID,
    project_id: UUID,
    asset_id: UUID,
) -> str:
    """Create a five-minute URL scoped to one owned image and project."""

    if settings.jwt_secret_key is None:
        raise RuntimeError("Worker reference signing is not configured.")
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": str(owner_id),
            "project_id": str(project_id),
            "asset_id": str(asset_id),
            "aud": "generation_worker",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        settings.jwt_secret_key.get_secret_value(),
        algorithm="HS256",
    )
    base_url = str(settings.public_api_base_url).rstrip("/")
    return f"{base_url}/api/v1/content/worker/assets/{asset_id}?{urlencode({'token': token})}"
