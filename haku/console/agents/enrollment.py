"""Typed application boundary for the browser half of Agent enrollment."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from haku.console.agents.models import AgentStatus, CredentialBindingStatus, CredentialKind


@dataclass(frozen=True, slots=True)
class EnrollmentBrowserSession:
    operator_id: UUID
    identity_id: UUID
    browser_session_id: str
    display_name: str


@dataclass(frozen=True, slots=True)
class ReconnectableAgent:
    agent_id: UUID
    display_name: str
    # NULL is accepted only for Agents created before durable policy assignment existed.
    auto_approval_policy: str | None


@dataclass(frozen=True, slots=True)
class EnrollmentPage:
    client_software: str
    redirect_host: str
    requested_scopes: tuple[str, ...]
    suggested_agent_name: str
    reconnectable_agents: tuple[ReconnectableAgent, ...]
    form_token: str
    upstream_authorization_url: str
    auto_approval_policies: tuple[str, ...]
    default_auto_approval_policy: str


@dataclass(frozen=True, slots=True)
class CreateAgentDecision:
    form_token: str
    display_name: str
    auto_approval_policy: str


@dataclass(frozen=True, slots=True)
class ReconnectAgentDecision:
    form_token: str
    agent_id: UUID
    auto_approval_policy: str


@dataclass(frozen=True, slots=True)
class DenyEnrollmentDecision:
    form_token: str


type EnrollmentDecision = CreateAgentDecision | ReconnectAgentDecision | DenyEnrollmentDecision


@dataclass(frozen=True, slots=True)
class EnrollmentAllowed:
    upstream_authorization_url: str


@dataclass(frozen=True, slots=True)
class EnrollmentDenied:
    pass


type EnrollmentDecisionResult = EnrollmentAllowed | EnrollmentDenied


class EnrollmentInteractionNotFoundError(LookupError):
    pass


class EnrollmentInteractionExpiredError(Exception):
    pass


class EnrollmentBrowserBindingError(PermissionError):
    pass


class EnrollmentDecisionConflictError(RuntimeError):
    pass


class AgentNameUnavailableError(ValueError):
    pass


class AutoApprovalPolicyUnavailableError(ValueError):
    pass


class AgentNotFoundError(LookupError):
    pass


class AgentAutoApprovalPolicyManagedByDeploymentError(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class OperatorAgent:
    agent_id: UUID
    display_name: str
    status: AgentStatus
    credential_kind: CredentialKind
    credential_status: CredentialBindingStatus
    created_at: datetime.datetime
    activated_at: datetime.datetime | None
    last_seen_at: datetime.datetime | None
    # NULL is accepted only for Agents created before durable policy assignment existed.
    auto_approval_policy: str | None


class AgentEnrollmentService(Protocol):
    def available_auto_approval_policies(self) -> tuple[str, ...]: ...

    async def list_agents(self, *, operator_id: UUID) -> tuple[OperatorAgent, ...]: ...

    async def set_auto_approval_policy(
        self, *, operator_id: UUID, agent_id: UUID, auto_approval_policy: str
    ) -> OperatorAgent: ...

    async def open_interaction(
        self,
        *,
        interaction_id: UUID,
        browser_nonce: str | None,
        interaction_cookie: str | None,
        browser: EnrollmentBrowserSession,
    ) -> EnrollmentPage: ...

    async def decide(
        self,
        *,
        interaction_id: UUID,
        browser: EnrollmentBrowserSession,
        interaction_cookie: str,
        decision: EnrollmentDecision,
    ) -> EnrollmentDecisionResult: ...
