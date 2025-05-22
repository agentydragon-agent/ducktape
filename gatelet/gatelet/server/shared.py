"""Shared resources for the Gatelet server."""

from datetime import timedelta
from pathlib import Path

from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def format_minutes(td: timedelta) -> str:
    """Return a human readable minutes string for ``td``."""

    minutes = td.total_seconds() / 60
    return f"{round(minutes)} min"


templates.env.filters["minutes"] = format_minutes
