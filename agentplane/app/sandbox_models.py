"""Configuration schemas shared by preset configuration and deployment rendering."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from agentplane.runner.harness import Harness

# Mirrors the CEL floor on `spec.idleSuspendAfter` in agentplane/sandboxes/api/types.go; the CRD is the authority.
MIN_IDLE_SUSPEND_AFTER_SECONDS = 60

InboxTag = Annotated[str, StringConstraints(min_length=1, max_length=63)]


class SessionDefaults(BaseModel):
    """Editable session launch fields; null means the caller deliberately left that field unspecified."""

    model_config = ConfigDict(extra="forbid")

    harness: Harness | None = None
    model: str | None = None
    cwd: str | None = None
    reasoning_effort: str | None = None
    instructions: str | None = None
    setup_script: str | None = Field(default=None, max_length=65_536)

    def over(self, base: SessionDefaults) -> SessionDefaults:
        """Replace only fields explicitly present in this object, including an explicit empty string."""
        return base.model_copy(update=self.model_dump(exclude_none=True))


class NewSandboxDefaults(BaseModel):
    """Initial lifecycle policies the operator may change on the Sandbox creation form."""

    model_config = ConfigDict(extra="forbid")

    wake_on_send: bool = Field(default=False, description="Whether the form starts with wake on message on.")
    idle_suspend_after_seconds: int | None = Field(
        default=None,
        ge=MIN_IDLE_SUSPEND_AFTER_SECONDS,
        description="The idle suspension time the form starts with; null starts it at never.",
    )
