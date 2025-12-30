"""Decorators for MCP tool handlers that depend on HabitifyClient.

Separated from utils/__init__.py to break circular import:
  habitify_client -> utils.date_utils -> utils/__init__ -> habitify_client
"""

from collections.abc import Callable
import functools
import os
from typing import Any, cast

from ..habitify_client import HabitifyClient, HabitifyError
from .error_utils import create_auth_error, create_error_response


def get_server_api_key() -> str | None:
    """Get API key from environment."""
    return os.environ.get("HABITIFY_API_KEY")


def with_api_key[F: Callable[..., Any]](func: F) -> F:
    """Decorator to inject the API key from server context or environment."""

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        api_key = get_server_api_key()
        if not api_key:
            raise HabitifyError(
                "API key is required. Set HABITIFY_API_KEY environment variable or configure server metadata."
            )

        if "api_key" not in kwargs:
            kwargs["api_key"] = api_key

        return await func(*args, **kwargs)

    return cast(F, wrapper)


def with_client[F: Callable[..., Any]](func: F) -> F:
    """Decorator to handle common client creation and error handling."""

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            api_key = get_server_api_key()
            if not api_key:
                return create_auth_error(
                    "API key is required. Set HABITIFY_API_KEY environment variable or configure server metadata."
                )

            async with HabitifyClient(api_key=api_key) as client:
                kwargs["client"] = client
                return await func(*args, **kwargs)
        except Exception as e:
            return create_error_response(e)

    return cast(F, wrapper)
