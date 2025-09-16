from __future__ import annotations

import asyncio
import uuid
from typing import Any, Callable, Literal, Optional

from adgn_llm.mini_codex.handler import (
    AbortTurnDecision,
    BeforeToolCallDecision,
    BypassToolInjectOutput,
    ContinueDecision,
)

# Control-plane exception raised when an approval decision requests aborting the turn
from mcp import types as mcp_types

from .mcp_manager import build_mcp_function, parse_mcp_function


class TurnAbortRequested(Exception):
    def __init__(
        self,
        call_id: str,
        reason: str = "approval_denied",
        context: Optional[dict] = None,
    ) -> None:
        self.call_id = call_id
        self.reason = reason
        self.context = context or {}
        super().__init__(f"Turn abort requested: {reason} (call_id={call_id})")


class ApprovalHub:
    """In-process rendezvous for pending approval/decision events.

    - await_decision(call_id, payload) -> BeforeToolCallDecision waits until resolve() is called
    - resolve(call_id, decision) resolves the pending decision
    """

    def __init__(self) -> None:
        self._futures: dict[str, asyncio.Future[BeforeToolCallDecision]] = {}
        self._lock = asyncio.Lock()

    async def await_decision(self, call_id: str, payload: dict[str, Any]) -> BeforeToolCallDecision:
        async with self._lock:
            fut = self._futures.get(call_id)
            if fut is None:
                fut = asyncio.get_running_loop().create_future()
                self._futures[call_id] = fut
        return await fut

    def resolve(self, call_id: str, decision: BeforeToolCallDecision) -> None:
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
            return await self._inner.call_tool(server, tool, arguments)

        # ask-mode
        call_id = f"appr-{uuid.uuid4().hex}"
        payload["call_id"] = call_id

        decision = await self._hub.await_decision(call_id, payload)

        # Pattern-match on the algebraic decision type
        if isinstance(decision, ContinueDecision):
            return await self._inner.call_tool(server, tool, arguments)

        if isinstance(decision, AbortTurnDecision):
            raise TurnAbortRequested(
                call_id=call_id,
                reason=decision.reason or "approval_denied",
                context=payload,
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
