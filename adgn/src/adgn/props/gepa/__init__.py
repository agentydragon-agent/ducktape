"""GEPA-based prompt optimization for props critic.

Uses gepa-ai/gepa for evolutionary optimization of the critic system prompt.
Implements GEPAAdapter protocol to integrate with your existing infrastructure:
- run_critic(): MiniCodex + Docker MCP
- grade_critique_by_id(): LLM grader
- Traces from events table
"""

from .gepa_adapter import (
    CriticAdapter,
    CriticOutput,
    CriticTrajectory,
    SnapshotInput,
    load_datasets,
    optimize_with_gepa,
)

__all__ = ["CriticAdapter", "CriticOutput", "CriticTrajectory", "SnapshotInput", "load_datasets", "optimize_with_gepa"]
