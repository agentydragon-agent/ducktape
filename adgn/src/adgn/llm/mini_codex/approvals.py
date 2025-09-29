from __future__ import annotations

import ast
import asyncio
from collections.abc import Callable
import json
import logging
from typing import Any, Literal, Optional, cast
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

# Control-plane exception raised when an approval decision requests aborting the turn
from mcp import types as mcp_types
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("mini_codex.approvals")

from adgn.llm.mini_codex.handler import (
    AbortTurnDecision,
    BeforeToolCallDecision,
    BypassToolInjectOutput,
    ContinueDecision,
    BaseHandler,
    ToolCall,
)

from .mcp_manager import build_mcp_function, parse_mcp_function


class TurnAbortRequested(Exception):
    def __init__(
        self,
        call_id: str,
        reason: str = "approval_denied",
        context: dict | None = None,
    ) -> None:
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

    - await_decision(call_id, request) -> BeforeToolCallDecision waits until resolve() is called
    - resolve(call_id, decision) resolves the pending decision
    """

    def __init__(self) -> None:
        self._futures: dict[str, asyncio.Future[BeforeToolCallDecision]] = {}
        self._requests: dict[str, ApprovalRequest] = {}
        self._lock = asyncio.Lock()

    async def await_decision(
        self,
        call_id: str,
        request: ApprovalRequest,
    ) -> BeforeToolCallDecision:
        async with self._lock:
            # Track the request so UIs can snapshot pending approvals
            self._requests[call_id] = request
            fut = self._futures.get(call_id)
            if fut is None:
                fut = asyncio.get_running_loop().create_future()
                self._futures[call_id] = fut
        return await fut

    def resolve(self, call_id: str, decision: BeforeToolCallDecision) -> None:
        fut = self._futures.pop(call_id, None)
        # Remove from pending requests map when resolved
        self._requests.pop(call_id, None)
        if fut is not None and not fut.done():
            fut.set_result(decision)


# Policy function type: given payload -> "allow" | "ask"
ApprovalMode = Literal["allow", "ask"]
ToolPolicyFn = Callable[[dict[str, Any]], ApprovalMode]


def default_allow_all_policy(_: dict[str, Any]) -> ApprovalMode:
    return "allow"


class McpManagerWithApprovals:
    """Opt-in wrapper that intercepts tool calls and consults an approval hub/provider.

    Contract (transparent wrapper over McpManager):
      - call_tool(namespaced: str, arguments: dict) -> mcp_types.CallToolResult
        * If policy(payload) == "allow": delegate to inner
        * If policy(payload) == "ask": create call_id, await decision via ApprovalHub
            - ContinueDecision -> delegate to inner
            - AbortTurnDecision -> raise TurnAbortRequested(call_id, reason)
            - BypassToolInjectOutput -> return provided CallToolResult (or synthesize one)
            - Unknown action -> crash (RuntimeError) per user instruction

    The wrapper exposes approval_hub for UI/drivers to resolve decisions.
    """

    def __init__(
        self,
        inner: Any,
        hub: ApprovalHub | None = None,
        tool_policy: ToolPolicyFn | None = None,
    ) -> None:
        self._inner = inner
        self._hub = hub or ApprovalHub()
        self._policy = tool_policy or default_allow_all_policy

    # ---- Pass-throughs ----
    async def list_tools(self, only: list[str] | None = None) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], await self._inner.list_tools(only=only))

    async def list_resources(
        self,
        only: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], await self._inner.list_resources(only=only))

    async def read_resource(self, server: str, uri: str) -> Any:
        # Pass-through in MVP; resource gating can be added similarly.
        return await self._inner.read_resource(server, uri)

    async def get_server_initialize(self, server: str):
        return await self._inner.get_server_initialize(server)

    @property
    def server_names(self) -> list[str]:
        return list(self._inner.server_names)

    # Preserve the same resolve_function shape if callers need it
    def resolve_function(self, namespaced: str) -> tuple[str, str]:
        return parse_mcp_function(namespaced)

    # ---- Interceptor: same signature as McpManager.call_tool (namespaced) ----
    async def call_tool(
        self,
        namespaced: str,
        arguments: dict[str, Any],
    ) -> mcp_types.CallToolResult:
        # Parse namespaced into (server, tool) for context and policy lookups
        server, tool = parse_mcp_function(namespaced)
        tool_key = build_mcp_function(server, tool)

        payload: dict[str, Any] = {
            "kind": "tool",
            "server": server,
            "tool": tool,
            "tool_key": tool_key,
            "arguments": arguments or {},
        }

        mode = self._policy(payload)
        if mode == "allow":
            return await self._inner.call_tool(server, tool, arguments)

        # ask-mode
        call_id = f"appr-{uuid.uuid4().hex}"
        req = ApprovalRequest(
            tool_key=tool_key,
            tool_call=ApprovalToolCall(
                name=tool,
                call_id=call_id,
                args_json=json.dumps(arguments or {}, ensure_ascii=False),
            ),
        )

        decision = await self._hub.await_decision(call_id, req)

        # Pattern-match on the algebraic decision type
        if isinstance(decision, ContinueDecision):
            return await self._inner.call_tool(server, tool, arguments)

        if isinstance(decision, AbortTurnDecision):
            raise TurnAbortRequested(
                call_id=call_id,
                reason=decision.reason or "approval_denied",
                context=req.model_dump(exclude_none=True),
            )

        if isinstance(decision, BypassToolInjectOutput):
            if decision.result is not None:
                return decision.result
            # synthesize a failure CallToolResult so agent gets a structured error
            return mcp_types.CallToolResult(
                content=[],
                isError=True,
                structuredContent={"ok": False, "error": f"User denied: {tool_key}"},
            )

        # Unknown approval decision: crash as requested by user
        raise RuntimeError(f"Unknown approval decision: {decision!r}")

    # ---- ApprovalHub control (for UI/driver) ----
    @property
    def approval_hub(self) -> ApprovalHub:
        return self._hub

    def resolve_approval(self, call_id: str, decision: BeforeToolCallDecision) -> None:
        self._hub.resolve(call_id, decision)

    # ---- Introspection for UIs (pending approvals) ----
    def pending(self) -> list[ApprovalRequest]:
        return list(self._hub._requests.values())


# ---- Approval Policy Engine (decoupled, in-memory; optional) ----


def validate_policy_python(source: str) -> None:
    """Validate that policy source is valid Python code.

    Raises ValueError if the source cannot be compiled as Python.
    """
    try:
        ast.parse(source)
    except SyntaxError as e:
        raise ValueError(f"Policy contains invalid Python syntax: {e}")
    except Exception as e:
        raise ValueError(f"Policy validation failed: {e}")


@dataclass
class Proposal:
    id: str
    source: str  # Python code defining the approval policy
    status: Literal["open", "approved", "rejected", "withdrawn"]
    created_at: datetime
    decided_at: Optional[datetime] = None
    rationale: Optional[str] = None  # Human-readable explanation for the policy change


class ProposalSnapshot(BaseModel):
    id: str
    status: Literal["open", "withdrawn", "approved", "rejected"]
    created_at: datetime
    decided_at: datetime | None = None
    source: str = Field(description="Python code defining the approval policy")
    rationale: str | None = Field(default=None, description="Human-readable explanation for the policy change")

    model_config = ConfigDict(from_attributes=True)


class ApprovalStatus(BaseModel):
    version: int
    open_proposal: str | None
    proposals: list[ProposalSnapshot]

    model_config = ConfigDict(from_attributes=True)


DEFAULT_APPROVAL_POLICY = '''def decide(ctx):
    """Default approval policy.

    Always allows:
    - UI communication tools (send_message, end_turn)
    - Approval policy management (get_status, propose, withdraw)
    - All resource operations (list, read) including policy.py and proposals
    - All operations on the approval_policy server

    Asks for approval on everything else.

    Args:
        ctx: Dict with keys: server, tool, tool_key, arguments

    Returns:
        "allow" | "ask" | "deny_continue" | "deny_abort"
    """
    tool_key = ctx.get("tool_key", "")
    server = ctx.get("server", "")

    # Always allow UI communication
    if tool_key in ("mcp__ui__send_message", "mcp__ui__end_turn"):
        return "allow"

    # Always allow approval policy management operations
    if tool_key in ("mcp__approval_policy__get_status",
                    "mcp__approval_policy__propose",
                    "mcp__approval_policy__withdraw"):
        return "allow"

    # Always allow reading and listing resources (including policy.py and proposals)
    if tool_key.startswith("mcp__resources__"):
        return "allow"

    # Allow reading resources directly from approval_policy server
    if server == "approval_policy":
        return "allow"

    # Ask for everything else by default
    return "ask"
'''


class ApprovalPolicyEngine:
    """Holds editable policy source and a single open proposal (in memory).

    Loose coupling: agent can run without this engine; servers/clients may react
    to notifications via an optional notifier callback.
    """

    def __init__(self, notifier: Callable[[str], None] | None = None) -> None:
        self._policy_source: str = DEFAULT_APPROVAL_POLICY
        self._policy_version: int = 1  # Start at 1 since we have default content
        self._proposals: dict[str, Proposal] = {}
        self._open_id: str | None = None
        # Notifier receives a resource URI (e.g., "approval-policy://policy.py" or proposals/{id}.json)
        self._notify = notifier

    def set_notifier(self, notifier: Callable[[str], None]) -> None:
        """Install/replace the out-of-band notifier for resource changes.

        Contract: notifier(uri) is sync and non-blocking (may schedule async work).
        """
        self._notify = notifier

    # --- Policy ---
    def get_policy(self) -> tuple[str, int]:
        return self._policy_source, self._policy_version

    def set_policy(self, source: str) -> int:
        # Validate policy is valid Python before applying
        validate_policy_python(source)
        self._policy_source = source
        self._policy_version += 1
        if self._notify:
            self._notify("approval-policy://policy.py")
        return self._policy_version

    def decide(self, ctx: dict[str, Any]) -> str:
        """Evaluate policy; returns one of: allow|deny_continue|deny_abort|ask.

        Executes the current policy if present, otherwise returns "ask".
        """
        src = (self._policy_source or "").strip()
        if not src:
            logger.debug("ApprovalPolicyEngine.decide: no policy source, returning 'ask'")
            return "ask"
        ns: dict[str, Any] = {}
        try:
            exec(src, {"__builtins__": {"__import__": __import__}}, ns)
            fn = ns.get("decide")
            if callable(fn):
                out = fn(dict(ctx))
                logger.debug(
                    "ApprovalPolicyEngine.decide: tool_key=%s, result=%s",
                    ctx.get("tool_key"),
                    out
                )
                if out in {"allow", "deny_continue", "deny_abort", "ask"}:
                    return cast(str, out)
        except Exception:
            # Fail fast so tests surface policy errors instead of hanging in ask-mode
            raise
        return "ask"

    # --- Proposals ---
    def create_proposal(self, source: str, rationale: str | None = None) -> str:
        # Validate proposed policy is valid Python before creating proposal
        validate_policy_python(source)
        if self._open_id is not None:
            raise RuntimeError("a proposal is already open")
        pid = f"p-{uuid.uuid4().hex}"
        now = datetime.now(timezone.utc)
        self._proposals[pid] = Proposal(
            id=pid, source=source, status="open", created_at=now, rationale=rationale
        )
        self._open_id = pid
        if self._notify:
            self._notify(f"approval-policy://proposals/{pid}.json")
        return pid

    def withdraw(self, pid: str) -> None:
        p = self._proposals.get(pid)
        if not p:
            return
        if p.status == "open":
            p.status = "withdrawn"
            p.decided_at = datetime.now(timezone.utc)
            if self._open_id == pid:
                self._open_id = None
            if self._notify:
                self._notify(f"approval-policy://proposals/{pid}.json")

    def apply(self, pid: str, decision: Literal["approve", "reject"]) -> None:
        p = self._proposals.get(pid)
        if not p:
            raise KeyError(pid)
        if p.status != "open":
            return
        p.status = "approved" if decision == "approve" else "rejected"
        p.decided_at = datetime.now(timezone.utc)
        if self._open_id == pid:
            self._open_id = None
        # Apply approved proposal to policy (emits policy.py notify)
        if p.status == "approved":
            self.set_policy(p.source)
        if self._notify:
            self._notify(f"approval-policy://proposals/{pid}.json")

    def get_status(self) -> ApprovalStatus:
        proposals = [
            ProposalSnapshot.model_validate(p) for p in self._proposals.values()
        ]
        return ApprovalStatus(
            version=self._policy_version,
            open_proposal=self._open_id,
            proposals=proposals,
        )

    # Proposal getters (server constructs resource URIs; engine provides data only)
    def get_proposal(self, pid: str) -> ProposalSnapshot:
        p = self._proposals.get(pid)
        if not p:
            raise KeyError(pid)
        return ProposalSnapshot.model_validate(p)


# ---- Agent handler for approvals (before_tool_call) ----
class ApprovalPolicyHandler(BaseHandler):
    """Agent handler that enforces approval policy at the agent boundary.

    Evaluates ApprovalPolicyEngine and, when needed, gates the tool call via an
    ApprovalHub rendezvous. Returns a BeforeToolCallDecision:
    - ContinueDecision → proceed with MCP tool execution
    - AbortTurnDecision → abort the turn
    - BypassToolInjectOutput → inject provided CallToolResult instead of calling MCP
    """

    def __init__(
        self,
        engine: ApprovalPolicyEngine | None,
        hub: ApprovalHub,
    ) -> None:
        self._engine = engine
        self._hub = hub
        # Handler requires a live ApprovalHub to gate ask-mode decisions
        if self._hub is None:
            raise ValueError("ApprovalPolicyHandler requires a non-None ApprovalHub")

    async def before_tool_call(self, evt: ToolCall) -> BeforeToolCallDecision:
        # If no engine configured, pass through
        if not self._engine:
            return ContinueDecision()

        # Build policy context from the tool call; arguments remain opaque JSON
        try:
            server, tool = parse_mcp_function(evt.name)
        except Exception:
            # If name isn't namespaced (shouldn't happen), allow by default
            return ContinueDecision()
        ctx = {
            "server": server,
            "tool": tool,
            "tool_key": build_mcp_function(server, tool),
            "arguments": json.loads(evt.args_json or "{}"),
        }

        mode = self._engine.decide(ctx)
        logger.debug(
            "ApprovalPolicyHandler decision: tool_key=%s, mode=%s",
            ctx.get("tool_key"),
            mode
        )
        if mode == "allow":
            return ContinueDecision()
        if mode == "deny_abort":
            return AbortTurnDecision(reason="policy_denied")
        if mode == "deny_continue":
            return BypassToolInjectOutput(
                result=mcp_types.CallToolResult(
                    content=[],
                    isError=True,
                    structuredContent={
                        "ok": False,
                        "error": f"policy denied: {ctx['tool_key']}",
                    },
                )
            )

        # ask: require hub for gating; if none, pass through
        if not self._hub:
            return ContinueDecision()

        # Use the real model-provided call_id to keep flows consistent end-to-end
        call_id = evt.call_id
        req = ApprovalRequest(
            tool_key=ctx["tool_key"],
            tool_call=ApprovalToolCall(
                name=tool,
                call_id=call_id,
                args_json=json.dumps(ctx["arguments"], ensure_ascii=False),
            ),
        )
        decision = await self._hub.await_decision(call_id, req)
        return decision
