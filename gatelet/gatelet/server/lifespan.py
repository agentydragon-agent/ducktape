"""Application lifespan management for Gatelet server.

Handles startup and shutdown of application-scoped resources (database engine, etc.).
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import get_settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application lifespan: startup and shutdown.

    - On startup: Initialize database engine and session factory
    - On shutdown: Dispose of database engine

    Args:
        app: FastAPI application instance

    Resources stored on app.state:
        - db_engine: AsyncEngine
        - db_session_factory: async_sessionmaker[AsyncSession]
    """
    # Startup
    logger.info("Starting Gatelet server...")
    settings = get_settings()

    # Create database engine
    engine = create_async_engine(
        str(settings.database.dsn), echo=False, future=True, pool_pre_ping=True
    )
    app.state.db_engine = engine
    logger.info(f"Database engine created for: {settings.database.dsn}")

    # Create session factory
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )
    app.state.db_session_factory = session_factory
    logger.info("Database session factory created")

    yield

    # Shutdown
    logger.info("Shutting down Gatelet server...")
    await engine.dispose()
    logger.info("Database engine disposed")
