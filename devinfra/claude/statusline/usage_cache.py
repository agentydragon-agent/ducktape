"""Cached client for the Claude subscription usage API.

Fetches 5-hour and 7-day utilization percentages from the usage endpoint.
Results are cached to disk so the statusline stays fast on repeated invocations.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel

from devinfra.claude.claude_api.usage import UsageResponse, fetch_usage

logger = logging.getLogger(__name__)

CACHE_TTL = timedelta(seconds=120)


class CachedUsage(BaseModel):
    fetched_at: datetime
    usage: UsageResponse


@dataclass
class UsageCache:
    path: Path

    def read(self) -> CachedUsage | None:
        try:
            return CachedUsage.model_validate_json(self.path.read_text())
        except (OSError, ValueError):
            return None

    def write(self, usage: UsageResponse) -> CachedUsage:
        now = datetime.now(UTC)
        cached = CachedUsage(fetched_at=now, usage=usage)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(cached.model_dump_json())
        except OSError:
            logger.debug("Could not write usage cache to %s", self.path)
        return cached

    def get(self, access_token: str | None) -> CachedUsage | None:
        """Return subscription usage, using cache when fresh enough."""
        cached = self.read()

        if cached is not None and datetime.now(UTC) - cached.fetched_at < CACHE_TTL:
            return cached

        if access_token is None:
            return cached

        try:
            fresh = fetch_usage(access_token)
        except Exception:
            logger.debug("Usage API fetch failed, using stale cache", exc_info=True)
            return cached

        return self.write(fresh)
