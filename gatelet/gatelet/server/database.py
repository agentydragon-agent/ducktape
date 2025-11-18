"""Database session management for Gatelet server."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .config import get_settings

# Global engine and session factory (lazy-initialized)
_engine: AsyncEngine | None = None
_async_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Get the global database engine (lazy-initialized, cached).

    Returns:
        AsyncEngine: SQLAlchemy async engine
    """
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(str(settings.database.dsn), echo=False, future=True, pool_pre_ping=True)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get the global session factory (lazy-initialized, cached).

    Returns:
        async_sessionmaker: SQLAlchemy async session factory
    """
    global _async_session_factory
    if _async_session_factory is None:
        engine = get_engine()
        _async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    return _async_session_factory


def reset_database() -> None:
    """Clear cached engine and session factory (primarily for testing)."""
    global _engine, _async_session_factory
    _engine = None
    _async_session_factory = None


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Get a database session.

    Returns:
        AsyncSession: Database session.
    """
    async_session_factory = get_session_factory()
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# Deprecated: Direct access to engine and async_session_factory is discouraged.
# Use get_engine() and get_session_factory() instead.
# These exist for backward compatibility during migration.
engine = get_engine()
async_session_factory = get_session_factory()
