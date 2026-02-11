"""PolicyEngine: Complete policy subsystem with servers, state, and middleware."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from enum import StrEnum
from importlib import resources
import json
import logging
from typing import TYPE_CHECKING, Any
import uuid

from docker.client import DockerClient
from fastmcp.client import Client
from fastmcp.server import FastMCP
from fastmcp.server.context import ServerSession
from fastmcp.server.middleware.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.tool import ToolResult
from jinja2 import Template
from mcp import McpError, types as mtypes
from mcp.types import ErrorData
from pydantic import AnyUrl, BaseModel

from adgn.agent.approvals import ApprovalRequest, ApprovalToolCall
from adgn.agent.handler import AbortTurnDecision, ContinueDecision
from adgn.agent.models.proposal_status import ProposalStatus
from adgn.agent.persist import ApprovalOutcome, Persistence
from adgn.agent.policies.policy_types import ApprovalDecision, PolicyRequest, PolicyResponse
from adgn.agent.policy_eval.container import ContainerPolicyEvaluator
from adgn.agent.policy_eval.runner import run_policy_source
from adgn.agent.types import AgentID
from adgn.mcp._shared.constants import (
    APPROVAL_POLICY_PROPOSALS_INDEX_URI,
    APPROVAL_POLICY_RESOURCE_URI,
    APPROVAL_POLICY_SERVER_NAME,
    PENDING_CALLS_URI,
    POLICY_BACKEND_RESERVED_MISUSE_CODE,
    POLICY_BACKEND_RESERVED_MISUSE_MSG,
    POLICY_DENIED_ABORT_CODE,
    POLICY_DENIED_ABORT_MSG,
    POLICY_DENIED_CONTINUE_CODE,
    POLICY_DENIED_CONTINUE_MSG,
    POLICY_EVALUATOR_ERROR_CODE,
    POLICY_EVALUATOR_ERROR_MSG,
    POLICY_GATEWAY_STAMP_KEY,
    RUNTIME_EXEC_TOOL_NAME,
    RUNTIME_SERVER_NAME,
    UI_SERVER_NAME,
)
from adgn.mcp._shared.naming import build_mcp_function
from adgn.mcp.notifying_fastmcp import NotifyingFastMCP

if TYPE_CHECKING:
    from adgn.mcp.compositor.server import Compositor

logger = logging.getLogger(__name__)


# ---- Enums for consolidated tools ----


class CallDecision(StrEnum):
    """Decision for a pending tool call."""

    APPROVE = "approve"
    DENY_ABORT = "deny_abort"
    DENY_CONTINUE = "deny_continue"


class ProposalDecision(StrEnum):
    """Decision for a policy proposal."""

    APPROVE = "approve"
    REJECT = "reject"


# ---- Pydantic models ----


class CreateProposalArgs(BaseModel):
    content: str


class WithdrawProposalArgs(BaseModel):
    id: str


class ProposalDescriptor(BaseModel):
    id: str
    status: ProposalStatus
    created_at: datetime
    decided_at: datetime | None = None


class DecideCallArgs(BaseModel):
    call_id: str
    decision: CallDecision


class DecideProposalArgs(BaseModel):
    proposal_id: str
    decision: ProposalDecision


class SetPolicyTextArgs(BaseModel):
    """Direct policy set input for admin endpoint."""

    source: str


class PendingCallItem(BaseModel):
    """Pending call approval request exposed to UI."""

    call_id: str
    tool_key: str
    args_json: str | None = None


# ---- Private ApprovalHub (internal to PolicyEngine) ----


class _ApprovalHub:
    """In-process rendezvous for pending approval/decision events.

    Internal to PolicyEngine - not exposed publicly.
    """

    def __init__(self, on_change: Callable[[], None]) -> None:
        self._futures: dict[str, asyncio.Future[ContinueDecision | AbortTurnDecision]] = {}
        self._requests: dict[str, ApprovalRequest] = {}
        self._lock = asyncio.Lock()
        self._on_change = on_change

    def _notify_change(self) -> None:
        self._on_change()

    async def await_decision(self, call_id: str, request: ApprovalRequest) -> ContinueDecision | AbortTurnDecision:
        async with self._lock:
            self._requests[call_id] = request
            fut = self._futures.get(call_id)
            if fut is None:
                fut = asyncio.get_running_loop().create_future()
                self._futures[call_id] = fut
            self._notify_change()
        return await fut

    def resolve(self, call_id: str, decision: ContinueDecision | AbortTurnDecision) -> None:
        fut = self._futures.pop(call_id, None)
        self._requests.pop(call_id, None)
        if fut is not None and not fut.done():
            fut.set_result(decision)
        self._notify_change()

    @property
    def pending(self) -> dict[str, ApprovalRequest]:
        """View of pending approval requests."""
        return self._requests


# ---- Gateway middleware helpers ----


def _raise_if_reserved_code(e: McpError, name: str) -> None:
    """Check if error uses reserved policy codes and raise appropriate error."""
    code: int | None = None
    msg: str | None = None
    stamped: bool = False
    error = e.error
    try:
        code = int(error.code)
    except Exception:
        code = None
    try:
        msg = str(error.message)
    except Exception:
        msg = None
    data = error.data
    if isinstance(data, dict) and data.get(POLICY_GATEWAY_STAMP_KEY) is True:
        stamped = True
    if msg is None:
        msg = str(e)
    if not stamped:
        for a in e.args:
            if isinstance(a, mtypes.ErrorData):
                data = a.data
                if isinstance(data, dict) and data.get(POLICY_GATEWAY_STAMP_KEY) is True:
                    stamped = True
                    break
            if isinstance(a, dict):
                try:
                    ad = mtypes.ErrorData.model_validate(a)
                    data = ad.data
                    if isinstance(data, dict) and data.get(POLICY_GATEWAY_STAMP_KEY) is True:
                        stamped = True
                        break
                except Exception:
                    data = a.get("data")
                    if isinstance(data, dict) and data.get(POLICY_GATEWAY_STAMP_KEY) is True:
                        stamped = True
                        break

    if (
        stamped
        or (code in (POLICY_DENIED_ABORT_CODE, POLICY_DENIED_CONTINUE_CODE, POLICY_EVALUATOR_ERROR_CODE))
        or (msg in (POLICY_DENIED_ABORT_MSG, POLICY_DENIED_CONTINUE_MSG, POLICY_EVALUATOR_ERROR_MSG))
    ):
        raise McpError(
            ErrorData(
                code=POLICY_BACKEND_RESERVED_MISUSE_CODE,
                message=POLICY_BACKEND_RESERVED_MISUSE_MSG,
                data={
                    POLICY_GATEWAY_STAMP_KEY: True,
                    "name": name,
                    "backend_code": code if code is not None else "unknown",
                },
            )
        )


_DENIAL_MAP: dict[ApprovalDecision, tuple[int, str]] = {
    ApprovalDecision.DENY_ABORT: (POLICY_DENIED_ABORT_CODE, POLICY_DENIED_ABORT_MSG),
    ApprovalDecision.DENY_CONTINUE: (POLICY_DENIED_CONTINUE_CODE, POLICY_DENIED_CONTINUE_MSG),
}


def _policy_denied_error(decision: ApprovalDecision, name: str, reason: str | None) -> McpError:
    code, msg = _DENIAL_MAP[decision]
    return McpError(
        ErrorData(
            code=code,
            message=msg,
            data={POLICY_GATEWAY_STAMP_KEY: True, "decision": str(decision), "name": name, "reason": reason},
        )
    )


# ---- PolicyGatewayMiddleware (internal to PolicyEngine) ----


class _PolicyGatewayMiddleware(Middleware):
    """Approval-enforcing middleware installed on the agent compositor.

    - Gates tools/call via policy evaluation
    - Denials raise explicit JSON-RPC errors using reserved codes/messages
    - ASK blocks until hub resolves to Continue/Abort
    """

    def __init__(
        self,
        *,
        hub: _ApprovalHub,
        evaluate_policy: Callable[[PolicyRequest], Awaitable[PolicyResponse]],
        record_outcome: Callable[[str, str, ApprovalOutcome], Awaitable[None]] | None = None,
    ) -> None:
        self._hub = hub
        self._evaluate = evaluate_policy
        self._record = record_outcome
        self._inflight: dict[str, str] = {}

    def has_inflight_calls(self) -> bool:
        """Check if there are any tool calls currently in flight."""
        return len(self._inflight) > 0

    def inflight_count(self) -> int:
        """Return the number of tool calls currently in flight."""
        return len(self._inflight)

    async def on_call_tool(self, context: MiddlewareContext[Any], call_next: CallNext[Any, ToolResult]) -> ToolResult:
        name = context.message.name
        arguments = context.message.arguments
        tool_key = name

        # Evaluate policy
        try:
            decision_res = await self._evaluate(PolicyRequest(name=name, arguments=arguments))
            decision = decision_res.decision
            rationale = decision_res.rationale
        except Exception as e:
            logger.warning("policy evaluator error", exc_info=e)
            raise McpError(
                ErrorData(
                    code=POLICY_EVALUATOR_ERROR_CODE,
                    message=POLICY_EVALUATOR_ERROR_MSG,
                    data={POLICY_GATEWAY_STAMP_KEY: True, "name": name, "reason": f"{type(e).__name__}: {e}"},
                )
            )

        logger.debug("Policy decision: %s → %s (%s)", name, decision, rationale or "")

        if decision is ApprovalDecision.ALLOW:
            if self._record is not None:
                await self._record("pg:" + uuid.uuid4().hex, tool_key, ApprovalOutcome.POLICY_ALLOW)

            call_id = uuid.uuid4().hex
            self._inflight[call_id] = tool_key
            try:
                return await call_next(context)
            except McpError as e:
                _raise_if_reserved_code(e, name)
                raise
            except Exception as e:
                s = str(e)
                if (
                    (POLICY_DENIED_ABORT_MSG in s)
                    or (POLICY_DENIED_CONTINUE_MSG in s)
                    or (POLICY_EVALUATOR_ERROR_MSG in s)
                ):
                    raise McpError(
                        ErrorData(
                            code=POLICY_BACKEND_RESERVED_MISUSE_CODE,
                            message=POLICY_BACKEND_RESERVED_MISUSE_MSG,
                            data={POLICY_GATEWAY_STAMP_KEY: True, "name": name, "backend_code": "unknown"},
                        )
                    )
                raise
            finally:
                self._inflight.pop(call_id, None)

        if decision is ApprovalDecision.DENY_ABORT:
            if self._record is not None:
                await self._record("pg:" + uuid.uuid4().hex, tool_key, ApprovalOutcome.POLICY_DENY_ABORT)
            raise _policy_denied_error(ApprovalDecision.DENY_ABORT, name, rationale)

        if decision is ApprovalDecision.DENY_CONTINUE:
            if self._record is not None:
                await self._record("pg:" + uuid.uuid4().hex, tool_key, ApprovalOutcome.POLICY_DENY_CONTINUE)
            raise _policy_denied_error(ApprovalDecision.DENY_CONTINUE, name, rationale)

        # ASK: block until resolved via hub
        call_id = "pg:" + uuid.uuid4().hex
        req = ApprovalRequest(
            tool_key=tool_key,
            tool_call=ApprovalToolCall(
                name=name, call_id=call_id, args_json=(json.dumps(arguments) if arguments else None)
            ),
        )
        decision_obj = await self._hub.await_decision(call_id, req)

        if isinstance(decision_obj, ContinueDecision):
            if self._record is not None:
                await self._record(call_id, tool_key, ApprovalOutcome.POLICY_ALLOW)
            try:
                return await call_next(context)
            except McpError as e:
                _raise_if_reserved_code(e, name)
                raise
        if isinstance(decision_obj, AbortTurnDecision):
            if self._record is not None:
                await self._record(call_id, tool_key, ApprovalOutcome.POLICY_DENY_ABORT)
            raise _policy_denied_error(ApprovalDecision.DENY_ABORT, name, decision_obj.reason)

        raise McpError(
            ErrorData(
                code=-32603,
                message="internal_error: unknown approval decision type",
                data={POLICY_GATEWAY_STAMP_KEY: True, "name": name, "decision_type": type(decision_obj).__name__},
            )
        )


# ---- Helper to load instructions ----


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


# ---- PolicyEngine ----


class PolicyEngine:
    """Complete policy subsystem - servers, state, and middleware.

    Owns:
    - reader: NotifyingFastMCP with evaluate_policy, policy resources, pending://calls
    - policy_proposer: FastMCP with propose/withdraw tools
    - admin: FastMCP with decide_call, decide_proposal, set_policy tools
    - _hub: Internal ApprovalHub for pending call coordination
    - _gateway: PolicyGatewayMiddleware to install on compositor
    """

    def __init__(
        self, *, docker_client: DockerClient, agent_id: AgentID, persistence: Persistence, policy_source: str
    ) -> None:
        # Policy state
        self._policy_source: str = policy_source
        self._policy_version: int = 1

        # Context for policy operations
        self.docker_client: DockerClient = docker_client
        self.agent_id: AgentID = agent_id
        self.persistence: Persistence = persistence

        # Broadcast coordination
        self._broadcast_version: int = 0
        self._broadcast_cond: asyncio.Condition = asyncio.Condition()
        self._bg_tasks: set[asyncio.Task] = set()

        # Create hub with on_change callback that broadcasts pending://calls
        self._hub = _ApprovalHub(on_change=self._on_hub_change)

        # Create owned servers
        self.reader = NotifyingFastMCP(name="reader", instructions=_load_instructions())
        self.policy_proposer = NotifyingFastMCP(name="policy_proposer", instructions=None)
        self.admin = NotifyingFastMCP(name="admin", instructions=None)

        # Register tools/resources on each server
        self._register_reader()
        self._register_proposer()
        self._register_admin()

        # Protocol-level resource subscriptions on reader
        self._session_subscriptions: defaultdict[ServerSession, set[AnyUrl]] = defaultdict(set)
        mcp_server = self.reader._mcp_server

        def _subscriptions() -> set[AnyUrl]:
            return self._session_subscriptions[mcp_server.request_context.session]

        @mcp_server.subscribe_resource()
        async def _subscribe(uri: AnyUrl):
            _subscriptions().add(uri)

        @mcp_server.unsubscribe_resource()
        async def _unsubscribe(uri: AnyUrl):
            _subscriptions().discard(uri)

        # Create gateway middleware (uses internal evaluate method)
        self._gateway = _PolicyGatewayMiddleware(
            hub=self._hub, evaluate_policy=self._evaluate_policy, record_outcome=self._record_outcome
        )

        # Internal reader client for gateway (created lazily)
        self._reader_client: Client | None = None

    @property
    def gateway(self) -> Middleware:
        """Middleware to install on agent compositor."""
        return self._gateway

    # ---- Internal methods ----

    def _on_hub_change(self) -> None:
        """Called when hub pending list changes - broadcast pending://calls."""
        task = asyncio.create_task(self._broadcast_and_signal(PENDING_CALLS_URI))
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    async def _evaluate_policy(self, request: PolicyRequest) -> PolicyResponse:
        """Evaluate policy for a tool call via Docker-backed evaluator."""
        evaluator = ContainerPolicyEvaluator(agent_id=self.agent_id, docker_client=self.docker_client, engine=self)
        return await evaluator.decide(request)

    async def _record_outcome(self, call_id: str, tool_key: str, outcome: ApprovalOutcome) -> None:
        """Record approval outcome to persistence."""
        await self.persistence.record_approval(
            agent_id=self.agent_id, call_id=call_id, tool_key=tool_key, outcome=outcome, decided_at=datetime.now(UTC)
        )

    # ---- Policy state methods ----

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
            input_payload=PolicyRequest(name=build_mcp_function(UI_SERVER_NAME, "send_message"), arguments={}),
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
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    def _notify_proposal_change(self, proposal_id: str) -> None:
        """Notify about a specific proposal change and the proposals index."""
        self._schedule_broadcast(f"{APPROVAL_POLICY_PROPOSALS_INDEX_URI}/{proposal_id}")
        self._schedule_broadcast(APPROVAL_POLICY_PROPOSALS_INDEX_URI)

    async def _broadcast_and_signal(self, uri: str) -> None:
        if uri == APPROVAL_POLICY_PROPOSALS_INDEX_URI:
            await self.reader.broadcast_resource_list_changed()
        else:
            await self.reader.broadcast_resource_updated(uri)
        async with self._broadcast_cond:
            self._broadcast_version += 1
            self._broadcast_cond.notify_all()

    # ---- Server registration ----

    def _register_reader(self) -> None:
        """Register resources and evaluate_policy tool on reader server."""

        @self.reader.resource(APPROVAL_POLICY_RESOURCE_URI, name="policy.py", mime_type="text/x-python")
        def active_policy() -> str:
            content, _version = self.get_policy()
            return content

        @self.reader.resource(APPROVAL_POLICY_PROPOSALS_INDEX_URI + "/{id}", name="proposal", mime_type="text/x-python")
        async def proposal_item(id: str) -> str:
            if (got := await self.persistence.get_policy_proposal(self.agent_id, id)) is None:
                raise KeyError(id)
            return got.content

        @self.reader.resource(PENDING_CALLS_URI, name="pending_calls", mime_type="application/json")
        def pending_calls() -> dict:
            """List all pending tool call approval requests."""
            items = [
                PendingCallItem(
                    call_id=call_id, tool_key=req.tool_key, args_json=req.tool_call.args_json if req.tool_call else None
                )
                for call_id, req in self._hub.pending.items()
            ]
            return {"pending": [item.model_dump() for item in items]}

        @self.reader.flat_model()
        async def evaluate_policy(input: PolicyRequest) -> PolicyResponse:
            """Evaluate a policy decision for a single tool call via Docker-backed evaluator."""
            return await self._evaluate_policy(input)

    def _register_proposer(self) -> None:
        """Register tools on proposer server: create_proposal, withdraw_proposal."""

        @self.policy_proposer.flat_model()
        async def create_proposal(input: CreateProposalArgs) -> dict:
            """Create a new policy proposal and return its descriptor."""
            new_id = await self.create_proposal(input.content)
            desc = ProposalDescriptor(
                id=new_id, status=ProposalStatus.PENDING, created_at=datetime.now(UTC), decided_at=None
            )
            return desc.model_dump(mode="json")

        @self.policy_proposer.flat_model()
        async def withdraw_proposal(input: WithdrawProposalArgs) -> None:
            """Withdraw a pending policy proposal by id."""
            await self.withdraw_proposal(input.id)

    def _register_admin(self) -> None:
        """Register tools on admin server: decide_call, decide_proposal, set_policy."""

        @self.admin.flat_model()
        async def decide_call(input: DecideCallArgs) -> dict:
            """Approve or deny a pending tool call."""
            call_id = input.call_id
            decision = input.decision

            if decision == CallDecision.APPROVE:
                self._hub.resolve(call_id, ContinueDecision())
            elif decision == CallDecision.DENY_ABORT:
                self._hub.resolve(call_id, AbortTurnDecision(reason="user_denied"))
            elif decision == CallDecision.DENY_CONTINUE:
                # Continue without executing - resolve with continue decision
                # The call is skipped but turn continues
                self._hub.resolve(call_id, ContinueDecision())
            return {"ok": True}

        @self.admin.flat_model()
        async def decide_proposal(input: DecideProposalArgs) -> dict:
            """Approve or reject a policy proposal."""
            proposal_id = input.proposal_id
            decision = input.decision

            if decision == ProposalDecision.APPROVE:
                await self.approve_proposal(proposal_id)
            elif decision == ProposalDecision.REJECT:
                await self.reject_proposal(proposal_id)
            return {"ok": True}

        @self.admin.flat_model()
        async def set_policy(input: SetPolicyTextArgs) -> dict:
            """Directly set active policy text after self-check."""
            self.self_check(input.source)
            self.set_policy(input.source)
            return {"ok": True}

    async def wait_for_broadcast(self, since_version: int | None = None) -> int:
        """Await the next completed broadcast and return the new version."""
        target = (since_version or 0) + 1
        async with self._broadcast_cond:
            await self._broadcast_cond.wait_for(lambda: self._broadcast_version >= target)
            return self._broadcast_version


# ---- Compositor attach helpers ----


async def attach_reader(comp: Compositor, engine: PolicyEngine, *, name: str = "reader") -> NotifyingFastMCP:
    """Attach the policy reader server (resources + evaluate_policy tool)."""
    await comp.mount_inproc(name, engine.reader)
    return engine.reader


async def attach_policy_proposer(comp: Compositor, engine: PolicyEngine, *, name: str = "policy_proposer") -> FastMCP:
    """Attach the policy proposer server (create/withdraw proposals)."""
    await comp.mount_inproc(name, engine.policy_proposer)
    return engine.policy_proposer


async def attach_admin(comp: Compositor, engine: PolicyEngine, *, name: str = "admin") -> FastMCP:
    """Attach the policy admin server (decide_call/decide_proposal/set_policy)."""
    await comp.mount_inproc(name, engine.admin)
    return engine.admin


async def attach_approval_policy_readonly(
    comp: Compositor, engine: PolicyEngine, *, name: str = APPROVAL_POLICY_SERVER_NAME
) -> NotifyingFastMCP:
    """Attach the policy reader server with the standard approval_policy name."""
    return await attach_reader(comp, engine, name=name)


async def attach_approval_policy_proposer(
    comp: Compositor, engine: PolicyEngine, *, name: str = "policy_proposer"
) -> FastMCP:
    """Attach the policy proposer server for creating/withdrawing proposals."""
    return await attach_policy_proposer(comp, engine, name=name)
