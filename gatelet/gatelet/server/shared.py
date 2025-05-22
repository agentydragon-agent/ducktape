"""Shared resources for the Gatelet server."""

from pathlib import Path

from fastapi.templating import Jinja2Templates

from .config import settings

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def ha_history_url(entity_id: str) -> str:
    """Build direct link to Home Assistant history page."""
    base = settings.home_assistant.api_url.rstrip("/")
    return f"{base}/history?entity_id={entity_id}"


templates.env.globals["ha_history_url"] = ha_history_url
