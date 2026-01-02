"""Utility functions for the Habitify MCP server."""

import os
from typing import Any

from ..config import load_api_key

STATUS_COLORS = {"completed": "green", "skipped": "yellow", "failed": "red", "none": "blue"}


def get_status_color(status: str) -> str:
    """Get the color code for a habit status."""
    return STATUS_COLORS.get(status.lower(), "white")


def format_rich_status(status: str) -> str:
    """Format a status string with Rich formatting."""
    color = get_status_color(status)
    return f"[{color}]{status.capitalize()}[/]"


def get_api_key_from_param_or_env(api_key_param: str | None = None) -> str | None:
    """Get API key from parameter or environment."""
    return load_api_key(api_key_override=api_key_param, exit_on_missing=False)


def get_server_api_key() -> str | None:
    """Get API key from environment."""
    return os.environ.get("HABITIFY_API_KEY")


def validate_required_params(*param_names: str, **params: Any) -> dict[str, Any] | None:
    """Validate that at least one of the specified parameters is not None."""
    filtered_params = {name: params.get(name) for name in param_names if name in params} if param_names else params

    if not any(value is not None for value in filtered_params.values()):
        param_list = ", ".join(filtered_params.keys())
        return {
            "error": f"At least one of these parameters is required: {param_list}",
            "params": list(filtered_params.keys()),
        }

    return None
