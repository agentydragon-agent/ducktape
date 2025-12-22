"""Agent type definitions for the unified agent system.

This module defines the AgentType enum and type-specific configuration models
used across all agent types (critic, grader, prompt_optimizer, freeform).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from adgn.props.ids import SnapshotSlug
from adgn.props.prompt_optimize.target_metric import TargetMetric


class AgentType(StrEnum):
    """Types of agents in the system.

    Each agent type has different:
    - MCP server class attached via MCP-over-HTTP
    - Handler configuration (run-to-completion vs conversational)
    - Database access (RLS policies)
    - Mount requirements
    """

    CRITIC = "critic"
    GRADER = "grader"
    PROMPT_OPTIMIZER = "prompt_optimizer"
    CLUSTERING = "clustering"  # Groups unknown issues into clusters
    IMPROVEMENT = "improvement"  # Analyzes runs and proposes improved prompts
    FREEFORM = "freeform"  # Ad-hoc sub-agents created by other agents


class CriticTypeConfig(BaseModel):
    """Critic-specific configuration.

    Critics analyze code snapshots and report issues.
    The full scope can be retrieved from the examples table via (snapshot_slug, scope_hash).
    """

    agent_type: Literal[AgentType.CRITIC] = AgentType.CRITIC
    snapshot_slug: SnapshotSlug  # Which snapshot to analyze
    scope_hash: str  # Identifies the scope (files to analyze), lookup via examples table


class GraderTypeConfig(BaseModel):
    """Grader-specific configuration.

    Graders evaluate critic output against ground truth.

    The snapshot_slug for RLS is derived at runtime from the graded critic's type_config
    via SQL: (SELECT type_config->>'snapshot_slug' FROM agent_runs WHERE agent_run_id = graded_agent_run_id).

    The canonical_issues_snapshot is populated at grading time and stores the TPs/FPs
    used during grading. This enables detecting stale grader runs after editing issue files.
    """

    agent_type: Literal[AgentType.GRADER] = AgentType.GRADER
    graded_agent_run_id: UUID  # The critic agent run being graded (must be a critic run)
    canonical_issues_snapshot: dict | None = None  # Populated at grading time (CanonicalIssuesSnapshot as dict)


class FreeformTypeConfig(BaseModel):
    """Freeform sub-agent configuration.

    Freeform agents are spawned by other agents (typically critics) for
    specialized tasks. They have minimal configuration - just the type marker.
    """

    agent_type: Literal[AgentType.FREEFORM] = AgentType.FREEFORM


class PromptOptimizerTypeConfig(BaseModel):
    """Prompt optimizer configuration.

    The target_metric controls validation split access:
    - WHOLE_REPO: TRAIN ground truth only, VALID metrics via SECURITY DEFINER function
                  (full-snapshot aggregates only)
    - TARGETED: TRAIN ground truth + VALID examples table (filenames only, no ground truth),
                VALID metrics via SECURITY DEFINER function (includes per-file aggregates)

    Both modes use SECURITY DEFINER functions for VALID metrics because:
    - Ground truth tables have TRAIN-only RLS
    - Aggregate views join ground truth tables, so inherit TRAIN-only restriction
    - Only SECURITY DEFINER can bypass RLS to compute VALID aggregates

    RLS uses current_prompt_optimizer_target_metric() to gate direct data access.
    """

    agent_type: Literal[AgentType.PROMPT_OPTIMIZER] = AgentType.PROMPT_OPTIMIZER
    target_metric: TargetMetric


class ClusteringTypeConfig(BaseModel):
    """Clustering agent configuration.

    Clustering agents group unknown issues (grader decisions with no TP match)
    into named clusters. They have direct SQL access to create clusters and
    assign unknowns.
    """

    agent_type: Literal[AgentType.CLUSTERING] = AgentType.CLUSTERING
    snapshot_slug: SnapshotSlug  # Which snapshot's unknowns to cluster


class AllowedExample(BaseModel, frozen=True):
    """A training example the improvement agent can access.

    Used in ImprovementTypeConfig.allowed_examples to specify which
    (snapshot_slug, scope_hash) pairs the agent can query via RLS.

    Frozen for use as dict keys/set members.
    """

    snapshot_slug: SnapshotSlug
    scope_hash: str


class ImprovementTypeConfig(BaseModel):
    """Improvement agent configuration.

    Improvement agents analyze critic/grader runs and propose improved agent definitions.

    RLS policies filter data access based on these fields:
    - Can read agent_definitions matching baseline_definition_ids
    - Can read agent_runs/events for runs on allowed_examples
    - Can create new definitions and run evals on allowed_examples
    """

    agent_type: Literal[AgentType.IMPROVEMENT] = AgentType.IMPROVEMENT
    baseline_definition_ids: list[str] = Field(
        min_length=1, description="One or more agent definition IDs to study and improve"
    )
    allowed_examples: list[AllowedExample] = Field(
        min_length=1, description="One or more (snapshot_slug, scope_hash) pairs to evaluate on"
    )


# Discriminated union for type-specific config
TypeConfig = Annotated[
    CriticTypeConfig
    | GraderTypeConfig
    | FreeformTypeConfig
    | PromptOptimizerTypeConfig
    | ClusteringTypeConfig
    | ImprovementTypeConfig,
    Field(discriminator="agent_type"),
]


class AgentConfig(BaseModel):
    """Full agent configuration for creating agent runs.

    Combines shared fields (definition, model, parent) with type-specific config.
    The type_config is stored as JSONB in the database and determines what
    MCP server, handlers, and mounts are used for the agent.

    Usage:
        config = AgentConfig(
            definition_id="critic",
            model="claude-sonnet-4-20250514",
            parent_agent_run_id=None,
            type_config=CriticTypeConfig(snapshot_slug="snap-123", scope_hash="abc"),
        )
        # Access agent type via property
        assert config.agent_type == AgentType.CRITIC
    """

    definition_id: str = Field(description="Agent definition ID (references agent_definitions.id)")
    model: str = Field(description="LLM model to use (e.g., 'claude-sonnet-4-20250514')")
    parent_agent_run_id: UUID | None = Field(
        default=None, description="Parent agent run ID for sub-agents (FK to agent_runs)"
    )
    type_config: TypeConfig = Field(description="Type-specific configuration (stored as JSONB)")

    @property
    def agent_type(self) -> AgentType:
        """Get the agent type from type_config discriminator."""
        return self.type_config.agent_type
