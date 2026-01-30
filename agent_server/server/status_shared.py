from __future__ import annotations

from pydantic import BaseModel, ConfigDict

"""Status models and builder (no host volumes reported)."""


class UiStateLite(BaseModel):
    ready: bool
    model_config = ConfigDict(extra="forbid")


class ContainerState(BaseModel):
    present: bool
    id: str | None
    model_config = ConfigDict(extra="forbid")
