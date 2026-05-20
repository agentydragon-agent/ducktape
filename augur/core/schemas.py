from __future__ import annotations

from pydantic import BaseModel, ConfigDict

# ---------------------------------------------------------------------------
# Base configurations.
# ---------------------------------------------------------------------------
#
# Shared simulator models use ordinary snake_case field names. App-specific
# HTTP boundaries may adapt those names for browser compatibility, but that
# conversion is not a core schema concern.


class CoreModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
