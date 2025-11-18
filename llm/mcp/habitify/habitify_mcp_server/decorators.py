"""
Function decorators for the Habitify MCP server.
"""

from collections.abc import Callable
import functools
from typing import Any, TypeVar, cast

from .habitify_client import HabitifyClient, HabitifyError
from .utils import create_auth_error, create_error_response, get_server_api_key

# Define type variables for function annotations
F = TypeVar("F", bound=Callable[..., Any])


def with_api_key(func: F) -> F:
    """
    Decorator to inject the API key from server context or environment.

    Args:
        func: Function to decorate

    Returns:
        Decorated function
    """

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        # Get API key
        api_key = get_server_api_key()
        if not api_key:
            raise HabitifyError(
                "API key is required. Set HABITIFY_API_KEY environment variable or configure server metadata."
            )

        # Add API key to kwargs if not already present
        if "api_key" not in kwargs:
            kwargs["api_key"] = api_key

        return await func(*args, **kwargs)

    return cast(F, wrapper)


def with_client(func: F) -> F:
    """
    Decorator to handle common client creation and error handling.

    Args:
        func: Function to decorate

    Returns:
        Decorated function
    """

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            # Get API key
            api_key = get_server_api_key()
            if not api_key:
                return create_auth_error(
                    "API key is required. Set HABITIFY_API_KEY environment variable or configure server metadata."
                )

            # Create client and call function
            async with HabitifyClient(api_key=api_key) as client:
                # Add client to kwargs
                kwargs["client"] = client
                return await func(*args, **kwargs)
        except Exception as e:
            return create_error_response(e)

    return cast(F, wrapper)


__all__ = [
    "with_api_key",
    "with_client",
]
