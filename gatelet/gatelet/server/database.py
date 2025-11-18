"""Database session management for Gatelet server."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from .shared import get_db_session_factory


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Get a database session (FastAPI dependency).

    Use as: db: AsyncSession = Depends(get_db_session)

    The session factory is managed by the application lifespan.
    Sessions are created per-request and automatically committed/rolled back.
    """
    factory = get_db_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
