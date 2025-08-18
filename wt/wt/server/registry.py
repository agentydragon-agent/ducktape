from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

Handler = Callable[..., Awaitable[Any]] | Callable[..., Any]

registry: dict[str, tuple[Handler, bool]] = {}


def register(method: str, *, needs_writer: bool = False):
    def decorator(func: Handler) -> Handler:
        registry[method] = (func, needs_writer)
        return func

    return decorator
