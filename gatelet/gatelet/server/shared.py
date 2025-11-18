"""Shared resources and utilities for the Gatelet server.

This module contains shared utilities like templates and template helpers.
Database resources are managed via FastAPI app.state in lifespan.py.
"""

from datetime import timedelta
from pathlib import Path

from fastapi import Depends
from fastapi.templating import Jinja2Templates

from .config import Settings, get_settings

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")


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
