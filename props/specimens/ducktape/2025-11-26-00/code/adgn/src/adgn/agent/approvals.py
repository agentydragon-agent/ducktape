from __future__ import annotations

import asyncio
from collections.abc import Callable
from enum import StrEnum
from importlib import resources
import logging
import uuid

from docker.client import DockerClient
from pydantic import BaseModel

from adgn.agent.handler import AbortTurnDecision, ContinueDecision
from adgn.agent.models.policy_error import PolicyError
from adgn.agent.persist import Persistence
from adgn.agent.policy_eval.runner import run_policy_source
from adgn.mcp._shared.constants import APPROVAL_POLICY_PROPOSALS_INDEX_URI, APPROVAL_POLICY_RESOURCE_URI, UI_SERVER_NAME
from adgn.mcp._shared.naming import build_mcp_function

# build_mcp_function is used for self_check payload construction

logger = logging.getLogger(__name__)


class PolicyValidationError(Exception):
    def __init__(self, message: str, details: PolicyError | None = None) -> None:
        super().__init__(message)
        self.details: PolicyError | None = details


# Policy source is executed only inside the container evaluator


# TODO(approval-policy follow-ups)
# - Resource operations are exposed as MCP tools (e.g., resources_list,
#   resources_read) and are gated by the Policy Gateway middleware.
#   The default policy allows RESOURCES server ops; tighten policy as needed.
# - Policy sandboxing: Execute user policy code under a stricter sandbox. Today
#   we execute with standard Python builtins and require explicit imports; future
#   hardening may restrict imports or isolate execution.
# - Persistence/versioning UX: Persistence exists (SQLite) for policy versions and
#   proposals, but richer history/metadata and rollback tools could improve UX.
# - Multi-user/editor UX: Add conflict prevention and richer notifications for
#   concurrent edits/approvals (e.g., optimistic locking, better UI affordances).


class TurnAbortRequested(Exception):  # noqa: N818
    # TODO: Reconsider whether signalling turn abort via exceptions is the best approach
    def __init__(self, call_id: str, reason: str = "approval_denied", context: dict | None = None) -> None:
        self.call_id = call_id
        self.reason = reason
        self.context = context or {}
        super().__init__(f"Turn abort requested: {reason} (call_id={call_id})")


class ApprovalToolCall(BaseModel):
    name: str
    call_id: str
    args_json: str | None = None


class ApprovalRequest(BaseModel):
    tool_key: str
    tool_call: ApprovalToolCall


class ApprovalHub:
    """In-process rendezvous for pending approval/decision events.

    - await_decision(call_id, request) -> ContinueDecision | AbortTurnDecision waits until resolve() is called
    - resolve(call_id, decision) resolves the pending decision
    """

    def __init__(self) -> None:
        self._futures: dict[str, asyncio.Future[ContinueDecision | AbortTurnDecision]] = {}
        self._requests: dict[str, ApprovalRequest] = {}
        self._lock = asyncio.Lock()

    async def await_decision(self, call_id: str, request: ApprovalRequest) -> ContinueDecision | AbortTurnDecision:
        async with self._lock:
            # Track the request so UIs can snapshot pending approvals
            self._requests[call_id] = request
            fut = self._futures.get(call_id)
            if fut is None:
                fut = asyncio.get_running_loop().create_future()
                self._futures[call_id] = fut
        return await fut

    def resolve(self, call_id: str, decision: ContinueDecision | AbortTurnDecision) -> None:
        fut = self._futures.pop(call_id, None)
        # Remove from pending requests map when resolved
        self._requests.pop(call_id, None)
        if fut is not None and not fut.done():
            fut.set_result(decision)

    @property
    def pending(self) -> dict[str, ApprovalRequest]:
        """Public view of pending approval requests (immutable contract by convention)."""
        return self._requests


# ---- Approval Policy Engine (decoupled, in-memory; optional) ----


class WellKnownTools(StrEnum):
    SEND_MESSAGE = "send_message"
    END_TURN = "end_turn"
    SANDBOX_EXEC = "sandbox_exec"  # adgn.mcp.seatbelt_exec.server


def load_default_policy_source() -> str:
    """Load the packaged default approval policy source code as text."""
    return resources.files("adgn.agent.policies").joinpath("default_policy.py").read_text(encoding="utf-8")


class ApprovalPolicyEngine:
    """Single source of truth for active policy text/version.

    Validation and execution are delegated to the Docker-backed evaluator. The
    engine stores text and publishes change notifications via the optional
    notifier callback.
    """

    def __init__(
        self,
        notifier: Callable[[str], None] | None = None,
        *,
        docker_client: DockerClient,
        agent_id: str,
        persistence: Persistence,
        policy_source: str,
    ) -> None:
        # DI of initial policy source; caller must pass explicit policy text.
        self._policy_source: str = policy_source
        self._policy_version: int = 1  # Start at 1 since we have default content
        # Notifier receives a canonical policy resource URI for broadcasts
        self._notify = notifier
        # Public attributes for engine wiring; keep simple access patterns
        self.docker_client: DockerClient = docker_client
        self.agent_id: str = agent_id
        self.persistence: Persistence = persistence

    def set_notifier(self, notifier: Callable[[str], None]) -> None:
        """Install/replace the out-of-band notifier for resource changes.

        Contract: notifier(uri) is sync and non-blocking (may schedule async work).
        """
        self._notify = notifier
        # No runtime volume state

    def get_policy(self) -> tuple[str, int]:
        return self._policy_source, self._policy_version

    def set_policy(self, source: str) -> int:
        # Store as-is; evaluator enforces correctness at call time
        self._policy_source = source
        self._policy_version += 1
        if self._notify:
            self._notify(APPROVAL_POLICY_RESOURCE_URI)
        return self._policy_version

    # Internal load used on startup to hydrate content/version from persistence
    def load_policy(self, source: str, *, version: int) -> None:
        # Hydrate from persistence without executing the code
        self._policy_source = source
        self._policy_version = version

    # No in-engine validation/TEST_CASES; evaluator will surface errors

    # No in-process evaluator construction; policy evaluation happens via MCP reader

    # Public attributes (no properties): docker_client, agent_id, persistence

    def self_check(self, source: str) -> None:
        run_policy_source(
            docker_client=self.docker_client,
            source=source,
            input_payload={"name": build_mcp_function(UI_SERVER_NAME, "send_message"), "arguments": {}},
        )

    def notify_resource(self, uri: str) -> None:
        cb = self._notify
        if cb:
            cb(uri)

    def notify_proposals_changed(self) -> None:
        cb = self._notify
        if cb:
            cb(APPROVAL_POLICY_PROPOSALS_INDEX_URI)

    def notify_proposal_change(self, proposal_id: str) -> None:
        """Notify about a specific proposal change and the proposals index.

        Convenience method that combines notifying about a specific proposal item
        and the proposals index list change.
        """
        self.notify_resource(f"{APPROVAL_POLICY_PROPOSALS_INDEX_URI}/{proposal_id}")
        self.notify_proposals_changed()

    async def create_proposal(self, content: str) -> str:
        """Create a new policy proposal and return its ID.

        Validates the proposal content if docker_client is available,
        persists it, and notifies about the change.
        """
        # Self-check proposal program if docker is available
        if self.docker_client is not None:
            self.self_check(content)
        # Generate new proposal ID and persist
        new_id = uuid.uuid4().hex
        await self.persistence.create_policy_proposal(self.agent_id, proposal_id=new_id, content=content)
        self.notify_proposal_change(new_id)
        return new_id

    async def withdraw_proposal(self, proposal_id: str) -> None:
        """Withdraw (delete) a pending policy proposal by ID."""
        await self.persistence.delete_policy_proposal(self.agent_id, proposal_id)
        self.notify_proposal_change(proposal_id)

    async def approve_proposal(self, proposal_id: str) -> None:
        """Approve a pending policy proposal by ID and activate it.

        Retrieves the proposal, validates it, activates it as the current policy,
        marks it approved in persistence, and notifies about the change.
        """
        got = await self.persistence.get_policy_proposal(self.agent_id, proposal_id)
        if got is None:
            raise KeyError(proposal_id)
        # Self-check the proposal program before activation
        if self.docker_client is not None:
            self.self_check(got.content)
        # Activate policy (notifies via engine's set_policy)
        self.set_policy(got.content)
        await self.persistence.approve_policy_proposal(self.agent_id, proposal_id)
        self.notify_proposal_change(proposal_id)

    async def reject_proposal(self, proposal_id: str) -> None:
        """Reject a pending policy proposal by ID."""
        await self.persistence.reject_policy_proposal(self.agent_id, proposal_id)
        self.notify_proposal_change(proposal_id)


def make_policy_engine(
    *,
    agent_id: str,
    persistence: Persistence,
    docker_client: DockerClient,
    notifier: Callable[[str], None] | None = None,
    policy_source: str,
) -> ApprovalPolicyEngine:
    """Factory for ApprovalPolicyEngine with required context.

    Centralizes creation for wiring, CLI, and tests without hiding parameters.
    """
    return ApprovalPolicyEngine(
        notifier, docker_client=docker_client, agent_id=agent_id, persistence=persistence, policy_source=policy_source
    )

    # No set_context: engine must be constructed with required context

    # No in-engine tests; proposals/policies are validated by executing in Docker

    # No in-process decide helpers

    # No proposal APIs here; proposals handled by approval policy server/persistence

    # No seatbelt resolution or policy fields here; keep context transport-agnostic

    # Default repr is sufficient; no custom string/repr implementation


# No agent-level approval handler: Policy Gateway middleware enforces approvals.
