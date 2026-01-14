"""Application lifespan management for Gatelet server.

Handles startup and shutdown of application-scoped resources (database engine, templates, etc.).
"""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import get_settings

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Manage application lifespan: startup and shutdown.

    - On startup: Initialize database engine, session factory, and templates
    - On shutdown: Dispose of database engine

    Args:
        app: FastAPI application instance

    Resources stored on app.state:
        - db_engine: AsyncEngine
        - db_session_factory: async_sessionmaker[AsyncSession]
        - templates: Jinja2Templates
    """
    # Startup
    logger.info("Starting Gatelet server...")
    settings = get_settings()

    # Create database engine
    engine = create_async_engine(str(settings.database.dsn), echo=False, future=True, pool_pre_ping=True)
    app.state.db_engine = engine
    logger.info(f"Database engine created for: {settings.database.dsn}")

    # Create session factory
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    app.state.db_session_factory = session_factory
    logger.info("Database session factory created")

    # Create templates instance
    app.state.templates = Jinja2Templates(directory=BASE_DIR / "templates")
    # Add Python builtins needed by templates
    app.state.templates.env.globals.update({"max": max, "min": min})
    logger.info("Templates initialized")

    yield

    # Shutdown
    logger.info("Shutting down Gatelet server...")
    await engine.dispose()
    logger.info("Database engine disposed")
