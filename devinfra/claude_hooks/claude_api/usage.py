"""Pydantic models for the Claude subscription usage API response."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


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
