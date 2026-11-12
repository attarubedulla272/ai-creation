"""Shared API test fixtures."""

import asyncio
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app import models  # noqa: F401
from app.core.config import Settings
from app.db.base import Base
from app.main import create_app


@pytest.fixture
def client(tmp_path) -> Iterator[TestClient]:
    """Provide an isolated SQLite-backed API client for a test."""

    database_path = tmp_path / "test.db"
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{database_path}",
        jwt_secret_key=SecretStr("test-only-secret-key-not-for-production-123"),
        cors_origins=["http://localhost:3000", "http://127.0.0.1:3101"],
        environment="test",
        storage_path=tmp_path / "storage",
    )
    application = create_app(settings)

    async def create_schema() -> None:
        async with application.state.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(create_schema())
    with TestClient(application) as test_client:
        yield test_client
