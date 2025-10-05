"""Utilities for Click-based command error handling."""

import asyncio
from collections.abc import Callable
import inspect
import threading

import click


def run_click_wrapped(verbose: bool, fn: Callable[..., object], *args, **kwargs) -> None:
    """Run a callable and convert exceptions to ClickException unless verbose is set.

    If the callable returns an awaitable, run it via asyncio.run. This keeps CLI
    command implementations concise for both sync and async handlers.
    """
    try:
        res = fn(*args, **kwargs)
        # Only run true coroutine objects; other awaitables (Futures, Tasks)
        # should be awaited by the caller that created them.
        if inspect.iscoroutine(res):
            # When a loop is already running (e.g., under pytest-asyncio),
            # asyncio.run would raise RuntimeError. In that case, execute the
            # coroutine in a dedicated thread with its own event loop.
            try:
                loop = asyncio.get_running_loop()
                loop_running = loop.is_running()
            except RuntimeError:
                loop_running = False

            if not loop_running:
                asyncio.run(res)
            else:
                exc_holder: list[BaseException | None] = [None]

                def _runner() -> None:
                    try:
                        asyncio.run(res)
                    except BaseException as e:  # pragma: no cover - surfaced to caller
                        exc_holder[0] = e

                t = threading.Thread(target=_runner, daemon=True)
                t.start()
                t.join()
                if exc_holder[0] is not None:
                    raise exc_holder[0]
    except Exception as e:  # pragma: no cover - passthrough to Click
        if verbose:
            raise
        raise click.ClickException(str(e)) from e
