"""Agent type definitions for the unified agent system.

This module defines the AgentType enum and type-specific configuration models
used across all agent types (critic, grader, prompt_optimizer, freeform).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field

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
    FREEFORM = "freeform"  # Ad-hoc sub-agents created by other agents


class CriticTypeConfig(BaseModel):
    """Critic-specific configuration.

    Critics analyze code snapshots and report issues.
    """

    agent_type: Literal[AgentType.CRITIC] = AgentType.CRITIC
    snapshot_slug: str  # Which snapshot to analyze
    scope_hash: str  # Identifies the scope (files to analyze)


class GraderTypeConfig(BaseModel):
    """Grader-specific configuration.

    Graders evaluate critic output against ground truth.
    """

    agent_type: Literal[AgentType.GRADER] = AgentType.GRADER
    graded_agent_run_id: UUID  # Must be a critic run (validated at creation)


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
    snapshot_slug: str  # Which snapshot's unknowns to cluster


# Discriminated union for type-specific config
TypeConfig = Annotated[
    CriticTypeConfig | GraderTypeConfig | FreeformTypeConfig | PromptOptimizerTypeConfig | ClusteringTypeConfig,
    Field(discriminator="agent_type"),
]
