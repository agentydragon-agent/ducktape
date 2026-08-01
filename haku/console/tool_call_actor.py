"""Authenticated actors in the Haku Console tool-call domain."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class OperatorActor:
    operator_id: UUID


@dataclass(frozen=True, slots=True)
class AgentActor:
    agent_id: UUID
    operator_id: UUID
    binding_id: UUID
    # Persisted per-Agent policy selection. ``None`` is the migration-safe, fail-closed default.
    auto_approval_policy: str | None = None


type ToolCallActor = OperatorActor | AgentActor
