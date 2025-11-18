"""Shared resources and state for the Gatelet server.

This module contains application-scoped state managed via lifespan and
shared utilities like templates.
"""

from datetime import timedelta
from pathlib import Path

from fastapi import Depends
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from .config import Settings, get_settings

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# Application state set by lifespan context manager
_db_engine: AsyncEngine | None = None
_db_session_factory: async_sessionmaker[AsyncSession] | None = None


def set_db_engine(engine: AsyncEngine) -> None:
    """Set the database engine (called during app lifespan startup)."""
    global _db_engine
    _db_engine = engine


def set_db_session_factory(factory: async_sessionmaker[AsyncSession]) -> None:
    """Set the database session factory (called during app lifespan startup)."""
    global _db_session_factory
    _db_session_factory = factory


def get_db_engine() -> AsyncEngine:
    """Get the database engine.

    Raises:
        RuntimeError: If called before app lifespan initialization
    """
    if _db_engine is None:
        raise RuntimeError("Database engine not initialized. Ensure app lifespan has started.")
    return _db_engine


def get_db_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get the database session factory.

    Raises:
        RuntimeError: If called before app lifespan initialization
    """
    if _db_session_factory is None:
        raise RuntimeError("Database session factory not initialized. Ensure app lifespan has started.")
    return _db_session_factory


def clear_db_state() -> None:
    """Clear database state (called during app lifespan shutdown and testing)."""
    global _db_engine, _db_session_factory
    _db_engine = None
    _db_session_factory = None


# Template helpers (use Depends for settings access)
def ha_history_url(entity_id: str, settings: Settings = Depends(get_settings)) -> str:
    """Build direct link to Home Assistant history page."""
    base = settings.home_assistant.api_url.rstrip("/")
    return f"{base}/history?entity_id={entity_id}"


def format_minutes(td: timedelta) -> str:
    """Return a human readable minutes string for ``td``."""
    minutes = td.total_seconds() / 60
    return f"{round(minutes)} min"


# Register template helpers (these use module-level settings for backward compatibility)
# TODO: Refactor templates to pass settings explicitly
from .config import get_settings as _get_settings_for_templates

_template_settings = _get_settings_for_templates()


def _ha_history_url_template(entity_id: str) -> str:
    """Template helper for ha_history_url (uses cached settings)."""
    base = _template_settings.home_assistant.api_url.rstrip("/")
    return f"{base}/history?entity_id={entity_id}"


templates.env.globals["ha_history_url"] = _ha_history_url_template
templates.env.filters["minutes"] = format_minutes
