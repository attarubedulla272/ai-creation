"""Start an isolated SQLite-backed API for the Video Editor browser tests."""

import asyncio
import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from pydantic import SecretStr

from app import models  # noqa: F401
from app.core.config import Settings
from app.db.base import Base
from app.main import create_app


def create_test_app() -> FastAPI:
    """Create the browser-test API and initialize its isolated database."""

    database_url = os.environ.get("DATABASE_URL")
    storage_path = os.environ.get("STORAGE_PATH")
    if not database_url or not storage_path:
        raise RuntimeError("DATABASE_URL and STORAGE_PATH are required for browser tests.")
    settings = Settings(
        database_url=database_url,
        jwt_secret_key=SecretStr("local-playwright-test-only-secret-key-123456"),
        environment="test",
        storage_path=Path(storage_path),
        cors_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:3101",
            os.environ.get("FRONTEND_TEST_ORIGIN", "http://127.0.0.1:3100"),
        ],
    )
    application = create_app(settings)

    async def create_schema() -> None:
        async with application.state.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        await application.state.engine.dispose()

    asyncio.run(create_schema())
    return application


if __name__ == "__main__":
    uvicorn.run(
        create_test_app(),
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "8101")),
        log_level="warning",
    )
