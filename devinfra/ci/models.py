"""Workflow configuration models for CI decision logic.

These models define our internal workflows.yaml format - trigger rules,
inputs, and secrets for each reusable workflow.

For GitHub Actions workflow schema (Step, Job, Workflow), see gha.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, Discriminator, Field, Tag


class AlwaysTrigger(BaseModel):
    """Workflow that always runs."""

    kind: Literal["always"] = "always"


class PathPatternTrigger(BaseModel):
    """Workflow triggered by file path pattern."""

    kind: Literal["path"] = "path"
    pattern: str


WorkflowTrigger = Annotated[
    Annotated[AlwaysTrigger, Tag("always")] | Annotated[PathPatternTrigger, Tag("path")], Discriminator("kind")
]


class WorkflowConfig(BaseModel):
    """Configuration for a workflow from workflows.yaml."""

    trigger: WorkflowTrigger
    inputs: dict[str, str] = Field(default_factory=dict)
    secrets: Literal["inherit"] | None = None
    rbe: bool = True
    events: frozenset[str] = frozenset({"push", "pull_request", "workflow_dispatch"})


class WorkflowManifest(BaseModel):
    """Collection of all workflow configurations."""

    workflows: dict[str, WorkflowConfig]

    @classmethod
    def from_yaml(cls, path: Path) -> WorkflowManifest:
        """Load from YAML file."""
        with path.open() as f:
            data = yaml.safe_load(f)
        return cls.model_validate(data)
