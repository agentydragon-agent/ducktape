"""Claude subscription usage API client with file-based caching.

Fetches 5-hour and 7-day utilization percentages from the undocumented
OAuth usage endpoint. Results are cached to disk so the statusline stays
fast on repeated invocations.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path

import httpx
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

logger = logging.getLogger(__name__)

USAGE_API_URL = "https://api.anthropic.com/api/oauth/usage"
CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"
CACHE_PATH = Path.home() / ".cache" / "claude-hooks" / "usage_cache.json"
CACHE_TTL_SECONDS = 120
API_TIMEOUT_SECONDS = 2.0


class _OAuthCredentials(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")

    access_token: str | None = None
    refresh_token: str | None = None
    expires_at: int | None = None
    scopes: list[str] | None = None
    subscription_type: str | None = None
    rate_limit_tier: str | None = None


class _McpOAuthEntry(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")

    server_name: str
    server_url: str
    client_id: str
    access_token: str
    expires_at: int
    refresh_token: str


class _Credentials(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")

    claude_ai_oauth: _OAuthCredentials | None = None
    mcp_oauth: dict[str, _McpOAuthEntry] | None = Field(default=None, alias="mcpOAuth")


class UsageBucket(BaseModel):
    model_config = ConfigDict(extra="ignore")

    utilization: float
    resets_at: datetime | None = None


class UsageResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    five_hour: UsageBucket | None = None
    seven_day: UsageBucket | None = None
    seven_day_opus: UsageBucket | None = None
    seven_day_sonnet: UsageBucket | None = None


class _CachedUsage(BaseModel):
    fetched_at: float
    usage: UsageResponse


def _read_access_token() -> str | None:
    """Read OAuth access token from Claude credentials file."""
    try:
        creds = _Credentials.model_validate_json(CREDENTIALS_PATH.read_text())
        return creds.claude_ai_oauth.access_token if creds.claude_ai_oauth else None
    except (OSError, ValueError):
        logger.debug("Could not read Claude OAuth token from %s", CREDENTIALS_PATH)
        return None


def _read_cache() -> _CachedUsage | None:
    try:
        return _CachedUsage.model_validate_json(CACHE_PATH.read_text())
    except (OSError, ValueError):
        return None


def _write_cache(usage: UsageResponse) -> None:
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(_CachedUsage(fetched_at=time.time(), usage=usage).model_dump_json())
    except OSError:
        logger.debug("Could not write usage cache to %s", CACHE_PATH)


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


def get_cached_usage() -> UsageResponse | None:
    """Return subscription usage, using cache when fresh enough."""
    cached = _read_cache()

    if cached is not None and time.time() - cached.fetched_at < CACHE_TTL_SECONDS:
        return cached.usage

    token = _read_access_token()
    if token is None:
        return cached.usage if cached else None

    fresh = _fetch_usage(token)
    if fresh is not None:
        _write_cache(fresh)
        return fresh

    return cached.usage if cached else None
