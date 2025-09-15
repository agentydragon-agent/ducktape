from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any, Literal, Optional, Protocol, Callable

from mcp import types as mcp_types

from .mcp_manager import parse_mcp_function, build_mcp_function


# Control-plane exception raised when an approval decision requests aborting the turn
class TurnAbortRequested(Exception):
    def __init__(self, call_id: str, reason: str = "approval_denied", context: Optional[dict] = None) -> None:
        self.call_id = call_id
        self.reason = reason
        self.context = context or {}
        super().__init__(f"Turn abort requested: {reason} (call_id={call_id})")


# Approval action space for providers / UI
ApprovalAction = Literal["allow", "deny_abort", "deny_with_result"]


@dataclass
class ApprovalDecision:
    action: ApprovalAction
    # When action == "deny_with_result", provider may supply a CallToolResult override
    result: Optional[mcp_types.CallToolResult] = None
    reason: Optional[str] = None


class ApprovalsProvider(Protocol):
    """Pluggable approvals provider.

    Implementations should return an ApprovalDecision. This model supports three outcomes:
      - allow: proceed to execute the real tool
      - deny_abort: abort the turn (raise TurnAbortRequested)
      - deny_with_result: do not execute the real tool, but return the provided CallToolResult so the agent can continue
    """

    async def decide(self, payload: dict[str, Any]) -> ApprovalDecision: ...


class ApprovalHub:
    """In-process rendezvous for pending approval decisions.

    - await_decision(call_id, payload) -> ApprovalDecision waits until resolve() is called
    - resolve(call_id, decision) resolves the pending decision
    """

    def __init__(self) -> None:
        self._futures: dict[str, asyncio.Future[ApprovalDecision]] = {}
        self._lock = asyncio.Lock()

    async def await_decision(self, call_id: str, payload: dict[str, Any]) -> ApprovalDecision:
        async with self._lock:
            fut = self._futures.get(call_id)
            if fut is None:
                fut = asyncio.get_running_loop().create_future()
                self._futures[call_id] = fut
        return await fut

    def resolve(self, call_id: str, decision: ApprovalDecision) -> None:
        fut = self._futures.pop(call_id, None)
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
            - decision.action == "allow" -> delegate to inner
            - decision.action == "deny_abort" -> raise TurnAbortRequested(call_id, reason)
            - decision.action == "deny_with_result" -> return provided CallToolResult (or synthesize one)
            - Unknown action -> crash (RuntimeError) per user instruction

    The wrapper exposes approval_hub for UI/drivers to resolve decisions.
    """

    def __init__(self, inner: Any, hub: ApprovalHub | None = None, tool_policy: ToolPolicyFn | None = None) -> None:
        self._inner = inner
        self._hub = hub or ApprovalHub()
        self._policy = tool_policy or default_allow_all_policy

    # ---- Pass-throughs ----
    async def list_tools(self, only: list[str] | None = None) -> list[dict[str, Any]]:
        return await self._inner.list_tools(only=only)

    async def list_resources(self, only: list[str] | None = None) -> list[dict[str, Any]]:
        return await self._inner.list_resources(only=only)

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
    async def call_tool(self, namespaced: str, arguments: dict[str, Any]) -> mcp_types.CallToolResult:
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
            return await self._inner.call_tool(namespaced, arguments)

        # ask-mode
        call_id = f"appr-{uuid.uuid4().hex}"
        payload["call_id"] = call_id

        decision = await self._hub.await_decision(call_id, payload)

        if decision.action == "allow":
            return await self._inner.call_tool(namespaced, arguments)

        if decision.action == "deny_abort":
            raise TurnAbortRequested(call_id=call_id, reason=decision.reason or "approval_denied", context=payload)

        if decision.action == "deny_with_result":
            if decision.result is not None:
                return decision.result
            # synthesize a failure CallToolResult so agent gets a structured error
            return mcp_types.CallToolResult(
                content=[],
                isError=True,
                structuredContent={"ok": False, "error": f"User denied: {tool_key}"},
            )

        # Unknown approval decision: crash as requested by user
        raise RuntimeError(f"Unknown approval decision action: {getattr(decision, 'action', None)!r}")

    # ---- ApprovalHub control (for UI/driver) ----
    @property
    def approval_hub(self) -> ApprovalHub:
        return self._hub

    def resolve_approval(self, call_id: str, decision: ApprovalDecision) -> None:
        self._hub.resolve(call_id, decision)
