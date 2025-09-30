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

from adgn.agent.handler import (
    AbortTurnDecision,
    BeforeToolCallDecision,
    BypassToolInjectOutput,
    ContinueDecision,
    BaseHandler,
    ToolCall,
)
from .mcp_manager import build_mcp_function, parse_mcp_function

logger = logging.getLogger("mini_codex.approvals")


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
    rationale: str | None = Field(
        default=None, description="Human-readable explanation for the policy change"
    )

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
        ctx: ApprovalContext with attributes: server, tool, tool_key, arguments

    Returns:
        "allow" | "ask" | "deny_continue" | "deny_abort"
    """
    server = ctx.server
    tool = ctx.tool

    # Always allow UI communication
    if server == "ui" and tool in ("send_message", "end_turn"):
        return "allow"

    # Always allow approval policy management operations
    if server == "approval_policy" and tool in ("get_status", "propose", "withdraw"):
        return "allow"

    # Always allow reading and listing resources (including policy.py and proposals)
    if server == "resources":
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

    def decide(self, ctx: "ApprovalContext") -> str:
        """Evaluate policy; returns one of: allow|deny_continue|deny_abort|ask.

        Executes the current policy if present, otherwise returns "ask".
        """
        src = (self._policy_source or "").strip()
        if not src:
            logger.debug(
                "ApprovalPolicyEngine.decide: no policy source, returning 'ask'"
            )
            return "ask"
        # Context must be an ApprovalContext (no dict backcompat)
        ctx_obj = ctx

        ns: dict[str, Any] = {}
        try:
            exec(src, {"__builtins__": {"__import__": __import__}}, ns)
            fn = ns.get("decide")
            if callable(fn):
                # Provide an object with attribute access; also supports dict-like .get
                out = fn(ctx_obj)
                logger.debug(
                    "ApprovalPolicyEngine.decide: server=%s tool=%s result=%s",
                    ctx_obj.server,
                    ctx_obj.tool,
                    out,
                )
                if out in {"allow", "deny_continue", "deny_abort", "ask"}:
                    return cast(str, out)
        except Exception:
            # Fail fast so tests surface policy errors instead of hanging in ask-mode
            raise
        return "ask"

    # --- Proposals ---
    def create_proposal(self, source: str, rationale: str | None = None) -> str:
        """Create a new open proposal for a policy change and return its id."""
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


class ApprovalContext:
    """Context object passed to approval policy with attribute and dict-like access.

    Attributes:
      - server: MCP server name (e.g., "docker", "resources")
      - tool: MCP tool name (e.g., "exec", "read")
      - arguments: dict of tool arguments (validated upstream)

    Convenience:
      - args alias to arguments
      - get(key, default) and __getitem__ for limited dict-compat
    """

    __slots__ = ("server", "tool", "arguments")

    def __init__(
        self,
        *,
        server: str,
        tool: str,
        arguments: dict[str, Any],
    ) -> None:
        self.server = server
        self.tool = tool
        self.arguments = arguments

    # Friendly alias
    @property
    def args(self) -> dict[str, Any]:
        return self.arguments

    # Dict-like helpers for backwards compatibility with policies using ctx.get
    def get(self, key: str, default: Any = None) -> Any:
        if key == "server":
            return self.server
        if key == "tool":
            return self.tool
        if key in {"arguments", "args"}:
            return self.arguments
        return default

    def __getitem__(self, key: str) -> Any:
        val = self.get(key, None)
        if val is None and key not in {"server", "tool", "arguments", "args"}:
            raise KeyError(key)
        return val

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return (
            f"ApprovalContext(server={self.server!r}, tool={self.tool!r}, "
            f"arguments={self.arguments!r})"
        )
        # (Engine handles proposals; context has no proposal API.)


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
        ctx = ApprovalContext(
            server=server,
            tool=tool,
            arguments=json.loads(evt.args_json or "{}"),
        )

        mode = self._engine.decide(ctx)
        logger.debug(
            "ApprovalPolicyHandler decision: server=%s tool=%s mode=%s",
            server,
            tool,
            mode,
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
                        "error": f"policy denied: {server}.{tool}",
                    },
                )
            )

        # ask: require hub for gating; if none, pass through
        if not self._hub:
            return ContinueDecision()

        # Use the real model-provided call_id to keep flows consistent end-to-end
        call_id = evt.call_id
        req = ApprovalRequest(
            tool_key=build_mcp_function(server, tool),
            tool_call=ApprovalToolCall(
                name=tool,
                call_id=call_id,
                args_json=json.dumps(ctx.arguments, ensure_ascii=False),
            ),
        )
        decision = await self._hub.await_decision(call_id, req)
        return decision
