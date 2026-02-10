"""Timing utilities for profiling test fixtures and operations."""

import logging
import time
from collections.abc import Generator
from contextlib import contextmanager

logger = logging.getLogger(__name__)


@contextmanager
def timed(label: str, log_level: int = logging.INFO) -> Generator[None]:
    """Context manager that logs elapsed time for a block.

    Usage:
        with timed("database.recreate"):
            database.recreate()

    Logs: "TIMING: database.recreate took 2.34s"
    """
    start = time.monotonic()
    try:
        yield
    finally:
        elapsed = time.monotonic() - start
        logger.log(log_level, "TIMING: %s took %.2fs", label, elapsed)
