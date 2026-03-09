"""Cached client for the Claude subscription usage API.

Fetches 5-hour and 7-day utilization percentages from the usage endpoint.
Results are cached to disk so the statusline stays fast on repeated invocations.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from pydantic import BaseModel

from devinfra.claude_hooks.claude_api.credentials import read_access_token
from devinfra.claude_hooks.claude_api.usage import USAGE_API_URL, UsageResponse

logger = logging.getLogger(__name__)

CACHE_PATH = Path.home() / ".cache" / "claude-hooks" / "usage_cache.json"
CACHE_TTL = timedelta(seconds=120)
API_TIMEOUT_SECONDS = 2.0


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


def _fetch_usage(token: str) -> UsageResponse | None:
    try:
        response = httpx.get(
            USAGE_API_URL,
            headers={"Authorization": f"Bearer {token}", "anthropic-beta": "oauth-2025-04-20"},
            timeout=API_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return UsageResponse.model_validate(response.json())
    except (httpx.HTTPError, ValueError):
        logger.debug("Usage API request failed", exc_info=True)
        return None


def get_cached_usage() -> CachedUsage | None:
    """Return subscription usage, using cache when fresh enough."""
    cached = _read_cache()

    if cached is not None and datetime.now(UTC) - cached.fetched_at < CACHE_TTL:
        return cached

    token = read_access_token()
    if token is None:
        return cached

    fresh = _fetch_usage(token)
    if fresh is not None:
        return _write_cache(fresh)

    return cached
