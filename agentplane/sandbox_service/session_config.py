"""Concrete session configuration stored on Sandboxes, independent of UI preset catalogs.

The storage codec preserves legacy annotation spelling independently of these public models.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Harness(StrEnum):
    """The runner protocol Harness enum names, reused by configuration and session projections."""

    CLAUDE = "HARNESS_CLAUDE"
    CODEX = "HARNESS_CODEX"


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

    def proto_json(self, session_id: str) -> dict[str, object]:
        values = self.model_dump(exclude_none=True, exclude={"setup_script"})
        if cwd := values.get("cwd"):
            values["cwd"] = str(cwd).replace("{session_id}", session_id)
        if harness := values.pop("harness", None):
            values["harness"] = str(harness)
        if "reasoning_effort" in values:
            values["reasoningEffort"] = values.pop("reasoning_effort")
        return values


class SandboxBinding(BaseModel):
    """The exact reusable session defaults and bootstrap the Sandbox was created with."""

    model_config = ConfigDict(extra="forbid")

    session_defaults: SessionDefaults | None = None
    bootstrap: str = Field(max_length=65_536)


class LaunchGrants(BaseModel):
    """Pending concrete policy grants, persisted on the Sandbox until provisioning completes."""

    model_config = ConfigDict(extra="forbid")

    policies: list[str]
    action_policy_sets: list[str]
