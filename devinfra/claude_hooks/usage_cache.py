"""Cached client for the Claude subscription usage API.

Fetches 5-hour and 7-day utilization percentages from the usage endpoint.
Results are cached to disk so the statusline stays fast on repeated invocations.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel

from devinfra.claude_hooks.claude_api.credentials import read_access_token
from devinfra.claude_hooks.claude_api.usage import UsageResponse, fetch_usage

logger = logging.getLogger(__name__)

CACHE_PATH = Path.home() / ".cache" / "claude-hooks" / "usage_cache.json"
CACHE_TTL = timedelta(seconds=120)


class CachedUsage(BaseModel):
    fetched_at: datetime
    usage: UsageResponse


def _read_cache() -> CachedUsage | None:
    try:
        return CachedUsage.model_validate_json(CACHE_PATH.read_text())
    except (OSError, ValueError):
        return None


def _write_cache(usage: UsageResponse) -> CachedUsage:
    now = datetime.now(UTC)
    cached = CachedUsage(fetched_at=now, usage=usage)
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(cached.model_dump_json())
    except OSError:
        logger.debug("Could not write usage cache to %s", CACHE_PATH)
    return cached


def get_cached_usage() -> CachedUsage | None:
    """Return subscription usage, using cache when fresh enough."""
    cached = _read_cache()

    if cached is not None and datetime.now(UTC) - cached.fetched_at < CACHE_TTL:
        return cached

    token = read_access_token()
    if token is None:
        return cached

    try:
        fresh = fetch_usage(token)
    except Exception:
        logger.debug("Usage API fetch failed, using stale cache", exc_info=True)
        return cached

    return _write_cache(fresh)
