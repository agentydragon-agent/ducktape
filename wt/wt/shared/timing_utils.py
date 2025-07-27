"""Timing utilities for operation measurement."""

import logging
import threading
import time
from contextlib import contextmanager
from typing import Any

# Thread-local nesting depth for verbose timing
_TIMING_DEPTH = threading.local()


@contextmanager
def timing(description: str):
    """Context manager for timing operations with proper logging."""
    timing_logger = logging.getLogger("wt.timing")

    # Only show timing if INFO level or higher is enabled
    if not timing_logger.isEnabledFor(logging.INFO):
        yield
        return

    depth = getattr(_TIMING_DEPTH, "depth", 0)
    import click

    click.echo(f"{'  ' * depth}→ {description}...")
    _TIMING_DEPTH.depth = depth + 1
    start = time.monotonic()
    try:
        yield
    finally:
        elapsed = time.monotonic() - start
        _TIMING_DEPTH.depth = getattr(_TIMING_DEPTH, "depth", 1) - 1
        depth = getattr(_TIMING_DEPTH, "depth", 0)
        click.echo(f"{'  ' * depth}✓ {description} completed in {elapsed:.3f}s")
