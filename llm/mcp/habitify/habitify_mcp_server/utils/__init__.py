"""
Utility functions for the Habitify MCP server.
"""

import os
from typing import Any, TypeVar

# Import API key getter from our config module
from ..config import load_api_key
from .date_utils import (
    create_date_range,
    format_date_for_api,
    format_date_human,
    format_date_yyyy_mm_dd,
    parse_date,
    validate_date_format,
)
from .error_utils import (
    classify_error,
    create_auth_error,
    create_error_response,
    create_not_found_error,
    create_validation_error,
)

# Define status colors mapping
STATUS_COLORS = {"completed": "green", "skipped": "yellow", "failed": "red", "none": "blue"}

# Define type variables for function annotations
T = TypeVar("T")


def get_status_color(status: str) -> str:
    """
    Get the color code for a habit status.

    Args:
        status: The status string (completed, skipped, failed, none)

    Returns:
        Color name for the given status
    """
    return STATUS_COLORS.get(status.lower(), "white")


def format_rich_status(status: str) -> str:
    """
    Format a status string with Rich formatting.

    Args:
        status: The status string (completed, skipped, failed, none)

    Returns:
        Rich-formatted status string with appropriate color
    """
    color = get_status_color(status)
    return f"[{color}]{status.capitalize()}[/]"


def get_api_key_from_param_or_env(api_key_param: str | None = None) -> str | None:
    """
    Get API key from parameter or environment.

    Args:
        api_key_param: Optional API key from command line parameter

    Returns:
        API key from parameter or environment variable
    """
    # Use our common config utility
    return load_api_key(api_key_override=api_key_param, exit_on_missing=False)


def get_server_api_key() -> str | None:
    """
    Get API key from environment.

    Returns:
        API key from environment variable or None
    """
    return os.environ.get("HABITIFY_API_KEY")


def validate_required_params(*param_names: str, **params: Any) -> dict[str, Any] | None:
    """
    Validate that at least one of the specified parameters is not None.

    Args:
        *param_names: Names of parameters to check
        **params: Parameter values to validate

    Returns:
        None if validation passed, or dict with error info if failed
    """
    # Filter to only include the specified parameters
    filtered_params = {name: params.get(name) for name in param_names if name in params} if param_names else params

    # Check if at least one parameter is not None
    if not any(value is not None for value in filtered_params.values()):
        param_list = ", ".join(filtered_params.keys())
        return {
            "error": f"At least one of these parameters is required: {param_list}",
            "params": list(filtered_params.keys()),
        }

    return None


__all__ = [
    # Status formatting
    "STATUS_COLORS",
    # Type variables
    "T",
    "classify_error",
    "create_auth_error",
    "create_date_range",
    # Error handling utilities
    "create_error_response",
    "create_not_found_error",
    "create_validation_error",
    "format_date_for_api",
    "format_date_human",
    "format_date_yyyy_mm_dd",
    "format_rich_status",
    # API key helpers
    "get_api_key_from_param_or_env",
    "get_server_api_key",
    "get_status_color",
    # Date utilities
    "parse_date",
    "validate_date_format",
    # Parameter validation
    "validate_required_params",
]
