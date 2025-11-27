import asyncio
from collections import defaultdict
from datetime import UTC, datetime
from importlib import resources
import logging
import uuid

from docker.client import DockerClient
from fastmcp.server.context import ServerSession
from jinja2 import Template
from pydantic import AnyUrl, BaseModel

from adgn.agent.models.proposal_status import ProposalStatus
from adgn.agent.persist import Persistence
from adgn.agent.policies.policy_types import PolicyRequest, PolicyResponse
from adgn.agent.policy_eval.container import ContainerPolicyEvaluator
from adgn.agent.policy_eval.runner import run_policy_source
from adgn.mcp._shared.constants import (
    APPROVAL_POLICY_PROPOSALS_INDEX_URI,
    APPROVAL_POLICY_RESOURCE_URI,
    APPROVAL_POLICY_SERVER_NAME_APPROVER,
    APPROVAL_POLICY_SERVER_NAME_PROPOSER,
    APPROVAL_POLICY_SERVER_NAME_READER,
    RUNTIME_EXEC_TOOL_NAME,
    RUNTIME_SERVER_NAME,
    UI_SERVER_NAME,
)
from adgn.mcp._shared.naming import build_mcp_function
from adgn.mcp.compositor.server import Compositor
from adgn.mcp.notifying_fastmcp import NotifyingFastMCP

logger = logging.getLogger(__name__)


class CreateProposalArgs(BaseModel):
    content: str


class WithdrawProposalArgs(BaseModel):
    id: str


class ProposalDescriptor(BaseModel):
    id: str
    status: ProposalStatus
    created_at: datetime
    decided_at: datetime | None = None


class ApproveProposalArgs(BaseModel):
    id: str


class RejectProposalArgs(BaseModel):
    id: str


class SetPolicyTextArgs(BaseModel):
    """Direct policy set input for admin endpoint.

    Uses field name 'source' to distinguish from proposal 'content'.
    """

    source: str


def _load_instructions() -> str:
    """Load and render instructions with embedded shared constants via Jinja2."""
    raw = resources.files(__package__).joinpath("instructions.j2.md").read_text(encoding="utf-8")
    tmpl = Template(raw)
    rendered = tmpl.render(
        RUNTIME_SERVER_NAME=RUNTIME_SERVER_NAME,
        RUNTIME_EXEC_TOOL_NAME=RUNTIME_EXEC_TOOL_NAME,
        TRUSTED_POLICY_PATH=None,
        TRUSTED_POLICY_URL=APPROVAL_POLICY_RESOURCE_URI,
    )
    return str(rendered)


class ApprovalPolicyServer(NotifyingFastMCP):
    """MCP server for approval policy: stores policy state, exposes resources and tools.

    This class combines the former ApprovalPolicyEngine (business logic) with the MCP
    server layer. Policy changes trigger MCP resource broadcasts directly, eliminating
    the notifier callback indirection.

    Exposes on self (reader):
    - Resources: policy.py, proposals/{id}
    - Tool: evaluate_policy()

    Owns sub-servers as attributes:
    - self.proposer: create_proposal, withdraw_proposal tools
    - self.approver: approve_proposal, reject_proposal, set_policy_text tools

    Exposes a deterministic waiter for tests via wait_for_broadcast(since_version).
    """

    def __init__(
        self,
        *,
        docker_client: DockerClient,
        agent_id: str,
        persistence: Persistence,
        policy_source: str,
        name: str = APPROVAL_POLICY_SERVER_NAME_READER,
    ) -> None:
        super().__init__(name=name, instructions=_load_instructions())

        # Policy state (formerly in ApprovalPolicyEngine)
        self._policy_source: str = policy_source
        self._policy_version: int = 1  # Start at 1 since we have default content

        # Context for policy operations
        self.docker_client: DockerClient = docker_client
        self.agent_id: str = agent_id
        self.persistence: Persistence = persistence

        # Broadcast coordination for deterministic waits (tests)
        self._broadcast_version: int = 0
        self._broadcast_cond: asyncio.Condition = asyncio.Condition()

        # Register resources and tools on self (reader server)
        self._register_resources()

        # Create owned sub-servers for proposer and approver roles
        self.proposer = NotifyingFastMCP(name=APPROVAL_POLICY_SERVER_NAME_PROPOSER, instructions=None)
        self.approver = NotifyingFastMCP(name=APPROVAL_POLICY_SERVER_NAME_APPROVER, instructions=None)
        self._register_proposer_tools()
        self._register_approver_tools()

        # Protocol-level resource subscriptions: acknowledge subscribe/unsubscribe
        # and maintain a minimal per-session index. Notifications are broadcast
        # by the server regardless of subscriptions, but handlers ensure that
        # capability gating reflects true support and calls succeed.
        self._session_subscriptions: defaultdict[ServerSession, set[AnyUrl]] = defaultdict(set)
        mcp_server = self._mcp_server

        def _subscriptions() -> set[AnyUrl]:
            """Return subscription set for current session context."""
            return self._session_subscriptions[mcp_server.request_context.session]

        @mcp_server.subscribe_resource()
        async def _subscribe(uri: AnyUrl):
            _subscriptions().add(uri)

        @mcp_server.unsubscribe_resource()
        async def _unsubscribe(uri: AnyUrl):
            _subscriptions().discard(uri)
            # Do not error if unknown; protocol allows idempotent unsubscribe

        # Do not expose a server-local "list subscriptions" resource; the
        # aggregator (resources server) provides a single index for the UI.

    # ---- Policy state methods (formerly ApprovalPolicyEngine) ----

    def get_policy(self) -> tuple[str, int]:
        """Return current policy source and version."""
        return self._policy_source, self._policy_version

    def set_policy(self, source: str) -> int:
        """Set new policy source and broadcast update."""
        self._policy_source = source
        self._policy_version += 1
        self._schedule_broadcast(APPROVAL_POLICY_RESOURCE_URI)
        return self._policy_version

    def load_policy(self, source: str, *, version: int) -> None:
        """Hydrate policy from persistence without broadcasting."""
        self._policy_source = source
        self._policy_version = version

    def self_check(self, source: str) -> None:
        """Validate policy source by executing it in Docker."""
        run_policy_source(
            docker_client=self.docker_client,
            source=source,
            input_payload={"name": build_mcp_function(UI_SERVER_NAME, "send_message"), "arguments": {}},
        )

    # ---- Proposal management methods ----

    async def create_proposal(self, content: str) -> str:
        """Create a new policy proposal and return its ID."""
        if self.docker_client is not None:
            self.self_check(content)
        new_id = uuid.uuid4().hex
        await self.persistence.create_policy_proposal(self.agent_id, proposal_id=new_id, content=content)
        self._notify_proposal_change(new_id)
        return new_id

    async def withdraw_proposal(self, proposal_id: str) -> None:
        """Withdraw (delete) a pending policy proposal by ID."""
        await self.persistence.delete_policy_proposal(self.agent_id, proposal_id)
        self._notify_proposal_change(proposal_id)

    async def approve_proposal(self, proposal_id: str) -> None:
        """Approve a pending policy proposal by ID and activate it."""
        got = await self.persistence.get_policy_proposal(self.agent_id, proposal_id)
        if got is None:
            raise KeyError(proposal_id)
        if self.docker_client is not None:
            self.self_check(got.content)
        self.set_policy(got.content)
        await self.persistence.approve_policy_proposal(self.agent_id, proposal_id)
        self._notify_proposal_change(proposal_id)

    async def reject_proposal(self, proposal_id: str) -> None:
        """Reject a pending policy proposal by ID."""
        await self.persistence.reject_policy_proposal(self.agent_id, proposal_id)
        self._notify_proposal_change(proposal_id)

    # ---- Notification helpers ----

    def _schedule_broadcast(self, uri: str) -> None:
        """Schedule async broadcast without blocking."""
        task = asyncio.create_task(self._broadcast_and_signal(uri))
        task.add_done_callback(lambda t: t.exception() if t.done() and not t.cancelled() else None)

    def _notify_proposal_change(self, proposal_id: str) -> None:
        """Notify about a specific proposal change and the proposals index."""
        self._schedule_broadcast(f"{APPROVAL_POLICY_PROPOSALS_INDEX_URI}/{proposal_id}")
        self._schedule_broadcast(APPROVAL_POLICY_PROPOSALS_INDEX_URI)

    async def _broadcast_and_signal(self, uri: str) -> None:
        if uri == APPROVAL_POLICY_PROPOSALS_INDEX_URI:
            await self.broadcast_resource_list_changed()
        else:
            await self.broadcast_resource_updated(uri)
        async with self._broadcast_cond:
            self._broadcast_version += 1
            self._broadcast_cond.notify_all()

    def _register_resources(self) -> None:
        # Resources for agents: active policy, proposals index and items
        @self.resource(APPROVAL_POLICY_RESOURCE_URI, name="policy.py", mime_type="text/x-python")
        def active_policy() -> str:
            content, _version = self.get_policy()
            return content

        @self.resource(APPROVAL_POLICY_PROPOSALS_INDEX_URI + "/{id}", name="proposal", mime_type="text/x-python")
        async def proposal_item(id: str) -> str:
            if (got := await self.persistence.get_policy_proposal(self.agent_id, id)) is None:
                raise KeyError(id)
            return got.content

        @self.flat_model()
        async def evaluate_policy(input: PolicyRequest) -> PolicyResponse:
            """Evaluate a policy decision for a single tool call via Docker-backed evaluator."""
            evaluator = ContainerPolicyEvaluator(
                agent_id=self.agent_id, docker_client=self.docker_client, engine=self
            )
            # Pass through input directly; it's already a PolicyRequest
            return await evaluator.decide(input)

    def _register_proposer_tools(self) -> None:
        """Register tools on self.proposer: create_proposal, withdraw_proposal."""

        @self.proposer.flat_model()
        async def create_proposal(input: CreateProposalArgs) -> ProposalDescriptor:
            """Create a new policy proposal and return its descriptor."""
            new_id = await self.create_proposal(input.content)
            return ProposalDescriptor(
                id=new_id, status=ProposalStatus.PENDING, created_at=datetime.now(UTC), decided_at=None
            )

        @self.proposer.flat_model()
        async def withdraw_proposal(input: WithdrawProposalArgs) -> None:
            """Withdraw a pending policy proposal by id."""
            await self.withdraw_proposal(input.id)

    def _register_approver_tools(self) -> None:
        """Register tools on self.approver: approve_proposal, reject_proposal, set_policy_text."""

        @self.approver.flat_model()
        async def approve_proposal(input: ApproveProposalArgs) -> None:
            """Approve a pending policy proposal by id (activates policy)."""
            await self.approve_proposal(input.id)

        @self.approver.flat_model()
        async def reject_proposal(input: RejectProposalArgs) -> None:
            """Reject a pending policy proposal by id."""
            await self.reject_proposal(input.id)

        @self.approver.flat_model()
        async def set_policy_text(input: SetPolicyTextArgs) -> None:
            """Directly set active policy text after self-check."""
            self.self_check(input.source)
            self.set_policy(input.source)

    async def wait_for_broadcast(self, since_version: int | None = None) -> int:
        """Await the next completed broadcast and return the new version.

        If since_version is provided, waits until a strictly higher version occurs.
        Use asyncio.timeout() around this call to add a timeout.
        """
        target = (since_version or 0) + 1
        async with self._broadcast_cond:
            await self._broadcast_cond.wait_for(lambda: self._broadcast_version >= target)
            return self._broadcast_version

    # No nested IO models; see module-level CreateProposalArgs/ProposalDescriptor


# ---- Compositor attach helpers ----


async def attach_approval_policy_readonly(
    comp: Compositor, policy_server: ApprovalPolicyServer, *, name: str = APPROVAL_POLICY_SERVER_NAME_READER
) -> ApprovalPolicyServer:
    """Attach the approval policy readonly server (resources + evaluate_policy tool).

    The policy_server itself is the reader server.
    """
    await comp.mount_inproc(name, policy_server)
    return policy_server


async def attach_approval_policy_proposer(
    comp: Compositor, policy_server: ApprovalPolicyServer, *, name: str = APPROVAL_POLICY_SERVER_NAME_PROPOSER
) -> NotifyingFastMCP:
    """Attach the approval policy proposer server (create/withdraw proposals).

    Uses policy_server.proposer which is an owned sub-server.
    """
    await comp.mount_inproc(name, policy_server.proposer)
    return policy_server.proposer


async def attach_approval_policy_admin(
    comp: Compositor, policy_server: ApprovalPolicyServer, *, name: str = APPROVAL_POLICY_SERVER_NAME_APPROVER
) -> NotifyingFastMCP:
    """Attach the approval policy admin server (approve/reject/set_policy_text).

    Uses policy_server.approver which is an owned sub-server.
    """
    await comp.mount_inproc(name, policy_server.approver)
    return policy_server.approver
