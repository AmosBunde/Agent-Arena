"""Async database access for the API service.

The API is async (system-design.md, Concurrency model); handlers await an
``AsyncSession`` provided by the ``get_session`` dependency. Tests override
the dependency with a session bound to a test container.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from apps.api.settings import ApiSettings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine(settings: ApiSettings | None = None) -> AsyncEngine:
    global _engine
    if _engine is None:
        resolved = settings or ApiSettings.from_env()
        _engine = create_async_engine(resolved.database_url, pool_pre_ping=True)
    return _engine


def get_session_factory(settings: ApiSettings | None = None) -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(bind=get_engine(settings), expire_on_commit=False)
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding one session per request."""
    factory = get_session_factory()
    async with factory() as session:
        yield session
