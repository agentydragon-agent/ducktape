"""App-owned form presets.

A preset is only a convenient collection of values the operator may choose individually. Kubernetes
and the runner receive the selected concrete template, policies, bootstrap source, and SessionSpec
fields, never a preset name to resolve later.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentplane.sandbox_service.session_config import Harness, ThreadDefaults


class ThreadPreset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    harness: Harness
    model: str
    cwd: str = "/state/workspaces/{session_id}"
    reasoning_effort: str | None = None
    instructions: str = ""
    setup_script: str = Field(default="", max_length=65_536)

    def defaults(self) -> ThreadDefaults:
        return ThreadDefaults.model_validate(self.model_dump(exclude={"title"}))


class SandboxPreset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    template: str
    policies: list[str] = Field(default_factory=list, description="EgressPolicy names every launch is granted.")
    action_policy_sets: list[str] = Field(
        default_factory=list,
        description="ActionPolicySet names every launch is bound to: what its harness may do without the operator.",
    )
    kubernetes_grants: list[str] = Field(
        default_factory=list, description="Enabled Kubernetes grant names to prefill at Sandbox launch."
    )
    thread_preset: str
    bootstrap: str = Field(default="", max_length=65_536)


class SandboxPresetView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    title: str
    template: str
    policies: list[str]
    action_policy_sets: list[str]
    kubernetes_grants: list[str]
    thread_defaults: ThreadDefaults
    bootstrap: str


class PresetCatalog(BaseModel):
    """Validated app configuration, keyed by names the UI may expand into editable fields."""

    model_config = ConfigDict(extra="forbid")

    sandboxes: dict[str, SandboxPreset] = Field(default_factory=dict)
    threads: dict[str, ThreadPreset] = Field(default_factory=dict)
    agent_instructions: str = Field(
        default="", description="Operational instructions prepended to every Agentplane-launched session."
    )

    @model_validator(mode="after")
    def _references_exist(self) -> PresetCatalog:
        missing = {
            preset.thread_preset for preset in self.sandboxes.values() if preset.thread_preset not in self.threads
        }
        if missing:
            raise ValueError(f"SandboxPresets name unknown ThreadPresets: {sorted(missing)}")
        return self

    def views(self) -> list[SandboxPresetView]:
        return [
            SandboxPresetView(
                name=name,
                title=preset.title,
                template=preset.template,
                policies=preset.policies,
                action_policy_sets=preset.action_policy_sets,
                kubernetes_grants=preset.kubernetes_grants,
                thread_defaults=self.threads[preset.thread_preset].defaults(),
                bootstrap=preset.bootstrap,
            )
            for name, preset in self.sandboxes.items()
        ]

    def instructions_for(self, task_instructions: str) -> str:
        """Combine platform operation guidance with the caller's task-specific instructions."""
        parts = [part.strip() for part in (self.agent_instructions, task_instructions) if part.strip()]
        return "\n\n".join(parts)
