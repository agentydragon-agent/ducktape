"""Pydantic models for the Claude subscription usage API response."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

# Undocumented Claude Code-specific endpoint for subscription utilization
# (5-hour / 7-day quotas). Not part of the official Anthropic Python SDK,
# which only exposes per-message token usage (anthropic.types.Usage).
USAGE_API_URL = "https://api.anthropic.com/api/oauth/usage"


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
