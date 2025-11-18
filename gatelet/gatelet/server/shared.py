"""Shared resources and utilities for the Gatelet server.

This module provides factory functions for templates and template helpers.
Database resources are managed via FastAPI app.state in lifespan.py.
"""

from pathlib import Path

from fastapi import Depends
from fastapi.templating import Jinja2Templates

from .config import Settings, get_settings

BASE_DIR = Path(__file__).parent


def get_jinja_templates() -> Jinja2Templates:
    """Create and return configured Jinja2 templates instance."""
    return Jinja2Templates(directory=BASE_DIR / "templates")


def make_ha_history_url(settings: Settings):
    """Create ha_history_url helper function bound to settings.

    Returns a function that can be passed to template context.
    Usage in templates: {{ ha_history_url(entity_id) }}
    """
    def helper(entity_id: str) -> str:
        base = settings.home_assistant.api_url.rstrip("/")
        return f"{base}/history?entity_id={entity_id}"
    return helper


# Template helpers (use Depends for settings access in endpoints)
def ha_history_url(entity_id: str, settings: Settings = Depends(get_settings)) -> str:
    """Build direct link to Home Assistant history page (for use in endpoints, not templates)."""
    base = settings.home_assistant.api_url.rstrip("/")
    return f"{base}/history?entity_id={entity_id}"
