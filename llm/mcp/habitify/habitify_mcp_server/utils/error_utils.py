"""
Error handling utilities for Habitify MCP.
"""

from typing import Any
from collections.abc import Callable

import httpx

from ..types import ErrorResponse

# Define a type for error handler functions
ErrorHandler = Callable[[Exception | str, dict[str, Any] | None], ErrorResponse]

# Error categories for better classification
ERROR_CATEGORIES = {
    "auth": "Authentication error",
    "not_found": "Resource not found",
    "validation": "Validation error",
    "api": "API error",
    "network": "Network error",
    "unknown": "Unknown error",
}


def classify_error(error: Exception) -> str:
    """
    Classify an error into one of the predefined categories.

    Args:
        error: The exception to classify

    Returns:
        The error category (auth, not_found, validation, api, network, unknown)
    """
    if isinstance(error, httpx.HTTPStatusError):
        status_code = error.response.status_code
        if status_code == 401 or status_code == 403:
            return "auth"
        elif status_code == 404:
            return "not_found"
        elif status_code == 400 or status_code == 422:
            return "validation"
        else:
            return "api"
    elif isinstance(error, httpx.ConnectError | httpx.TimeoutException):
        return "network"
    elif isinstance(error, ValueError):
        return "validation"
    return "unknown"


def _create_error_base(
    error_message: str | Exception,
    context: dict[str, Any] | None = None,
    category: str | None = None,
) -> ErrorResponse:
    """
    Internal function to create an error response with common handling.

    Args:
        error_message: String message or Exception
        context: Additional context to include in the response
        category: Error category (auth, not_found, validation, api, network, unknown)

    Returns:
        Error response model
    """
    # Create base error data
    error_text = str(error_message)
    error_data = {"error": error_text}

    # Add error category if provided
    if category and category in ERROR_CATEGORIES:
        error_data["category"] = category
    elif isinstance(error_message, Exception):
        error_data["category"] = classify_error(error_message)

    # Add any additional context
    if context:
        error_data.update(context)

    # Create and validate with Pydantic
    return ErrorResponse(**error_data)


def create_error_response(
    error: Exception,
    context: dict[str, Any] | None = None,
) -> ErrorResponse:
    """
    Create a simple error response that forwards the original error message.

    Args:
        error: The exception that occurred
        context: Additional context to include in the response

    Returns:
        Error response model
    """
    category = classify_error(error)
    return _create_error_base(error, context, category)


def create_validation_error(message: str, context: dict[str, Any] | None = None) -> ErrorResponse:
    """
    Create a validation error response for parameter validation failures.

    Args:
        message: The error message
        context: Additional context to include in the response

    Returns:
        Error response model
    """
    return _create_error_base(message, context, "validation")


def create_not_found_error(message: str, context: dict[str, Any] | None = None) -> ErrorResponse:
    """
    Create a not found error response.

    Args:
        message: The error message
        context: Additional context to include in the response

    Returns:
        Error response model
    """
    return _create_error_base(message, context, "not_found")


def create_auth_error(message: str, context: dict[str, Any] | None = None) -> ErrorResponse:
    """
    Create an authentication error response.

    Args:
        message: The error message
        context: Additional context to include in the response

    Returns:
        Error response model
    """
    return _create_error_base(message, context, "auth")
