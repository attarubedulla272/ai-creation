"""Async SQLAlchemy engine and request-scoped sessions."""

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings
from app.core.errors import APIError


def create_session_factory(
    settings: Settings,
) -> tuple[AsyncEngine | None, async_sessionmaker[AsyncSession] | None]:
    """Create the asynchronous database resources when a URL is configured."""

    if not settings.database_url:
        return None, None
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield a request-scoped database session or report missing configuration."""

    session_factory = request.app.state.session_factory
    if session_factory is None:
        raise APIError(
            503,
            "database_not_configured",
            "Database is not configured. Set DATABASE_URL and apply migrations.",
        )
    async with session_factory() as session:
        yield session
