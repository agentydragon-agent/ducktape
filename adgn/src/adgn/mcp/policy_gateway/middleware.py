from __future__ import annotations

from collections.abc import Awaitable, Callable
import json
import logging
from typing import Any
import uuid

from fastmcp.server.middleware.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.tool import ToolResult
from mcp import McpError, types as mtypes
from mcp.types import ErrorData

from adgn.agent.approvals import ApprovalHub, ApprovalRequest, ApprovalToolCall
from adgn.agent.handler import AbortTurnDecision, ContinueDecision
from adgn.agent.persist import ApprovalOutcome
from adgn.agent.policies.policy_types import ApprovalDecision, PolicyRequest
from adgn.mcp._shared.constants import (
    POLICY_BACKEND_RESERVED_MISUSE_CODE,
    POLICY_BACKEND_RESERVED_MISUSE_MSG,
    POLICY_DENIED_ABORT_CODE,
    POLICY_DENIED_ABORT_MSG,
    POLICY_DENIED_CONTINUE_CODE,
    POLICY_DENIED_CONTINUE_MSG,
    POLICY_EVALUATOR_ERROR_CODE,
    POLICY_EVALUATOR_ERROR_MSG,
    POLICY_GATEWAY_STAMP_KEY,
)
from adgn.mcp.approval_policy.clients import PolicyReaderStub

logger = logging.getLogger(__name__)


def _raise_if_reserved_code(e: McpError, name: str) -> None:
    # Some backends may rewrap or drop the ErrorData; handle both code and message checks.
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
    # Inspect args for embedded ErrorData/dict with stamp (in-proc raises may drop .error)
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


class PolicyGatewayMiddleware(Middleware):
    """Approval-enforcing middleware installed on the aggregating FastMCP server.

    - Gates tools/call via the provided policy evaluator and ApprovalHub
    - Denials raise explicit JSON-RPC errors using reserved codes/messages
    - ASK blocks until ApprovalHub resolves to Continue/Abort/Bypass
    """

    def __init__(
        self,
        *,
        hub: ApprovalHub,
        pending_notifier: Callable[[str, str, str | None], Awaitable[None]] | None = None,
        record_outcome: Callable[[str, str, ApprovalOutcome], Awaitable[None]] | None = None,
        policy_reader: PolicyReaderStub,
    ) -> None:
        self._hub = hub
        self._notify = pending_notifier
        self._record = record_outcome
        self._policy_reader = policy_reader
        # Track in-flight tool calls (call_id -> tool_key)
        self._inflight: dict[str, str] = {}

    def has_inflight_calls(self) -> bool:
        """Check if there are any tool calls currently in flight (not blocked by approval)."""
        return len(self._inflight) > 0

    def inflight_count(self) -> int:
        """Return the number of tool calls currently in flight."""
        return len(self._inflight)

    async def on_call_tool(self, context: MiddlewareContext[Any], call_next: CallNext[Any, ToolResult]) -> ToolResult:
        name = context.message.name
        arguments = context.message.arguments
        tool_key = name  # canonical function name

        # Evaluate decision via MCP reader server when available; fallback to local evaluator
        try:
            decision_res = await self._policy_reader.decide(PolicyRequest(name=name, arguments=arguments))
            decision = decision_res.decision
            rationale = decision_res.rationale
        except Exception as e:  # policy engine failure → explicit evaluator error
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

            # Track in-flight tool call
            call_id = uuid.uuid4().hex
            self._inflight[call_id] = tool_key
            try:
                call_result = await call_next(context)
                # If downstream returned an error ToolResult instead of raising,
                # remap reserved policy codes/messages here using typed parsing when available.
                if bool(getattr(call_result, "is_error", False)):
                    # Parse error details - ErrorData guarantees code: int per MCP/JSON-RPC spec
                    err = getattr(call_result, "error", None)
                    if err is None:
                        return call_result

                    # Try parsing as ErrorData (validates code is int, message is str)
                    try:
                        ed = mtypes.ErrorData.model_validate(err)
                    except Exception:
                        # Non-conforming error format - pass through
                        return call_result

                    # Check if error uses reserved policy codes/messages
                    stamped_downstream = isinstance(ed.data, dict) and ed.data.get(POLICY_GATEWAY_STAMP_KEY) is True
                    if (
                        stamped_downstream
                        or ed.code
                        in (POLICY_DENIED_ABORT_CODE, POLICY_DENIED_CONTINUE_CODE, POLICY_EVALUATOR_ERROR_CODE)
                        or ed.message
                        in (POLICY_DENIED_ABORT_MSG, POLICY_DENIED_CONTINUE_MSG, POLICY_EVALUATOR_ERROR_MSG)
                    ):
                        raise McpError(
                            ErrorData(
                                code=POLICY_BACKEND_RESERVED_MISUSE_CODE,
                                message=POLICY_BACKEND_RESERVED_MISUSE_MSG,
                                data={POLICY_GATEWAY_STAMP_KEY: True, "name": name, "backend_code": ed.code},
                            )
                        )
                return call_result
            except McpError as e:
                _raise_if_reserved_code(e, name)
                raise
            except Exception as e:
                # Some servers may translate backend McpError into a ToolError before it reaches us.
                # As a last resort, remap by inspecting the exception text.
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
                # Remove from in-flight tracking when call completes (success or error)
                self._inflight.pop(call_id, None)

        if decision is ApprovalDecision.DENY_ABORT:
            if self._record is not None:
                await self._record("pg:" + uuid.uuid4().hex, tool_key, ApprovalOutcome.POLICY_DENY_ABORT)
            raise _policy_denied_error(ApprovalDecision.DENY_ABORT, name, rationale)

        if decision is ApprovalDecision.DENY_CONTINUE:
            if self._record is not None:
                await self._record("pg:" + uuid.uuid4().hex, tool_key, ApprovalOutcome.POLICY_DENY_CONTINUE)
            raise _policy_denied_error(ApprovalDecision.DENY_CONTINUE, name, rationale)

        # ASK: block until resolved via ApprovalHub
        call_id = "pg:" + uuid.uuid4().hex
        req = ApprovalRequest(
            tool_key=tool_key,
            tool_call=ApprovalToolCall(
                name=name, call_id=call_id, args_json=(json.dumps(arguments) if arguments else None)
            ),
        )
        # Register + notify before awaiting
        wait_coro = self._hub.await_decision(call_id, req)
        if self._notify is not None:
            await self._notify(call_id, tool_key, req.tool_call.args_json)

        decision_obj = await wait_coro

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
            # No separate deny-continue decision; only abort is supported explicitly.
            # If UI wants to deny without abort, close the approval request without resolving;
            # the call will remain blocked until policy ALLOW arrives.

            # Unknown decision type: internal error for visibility
            raise McpError(
                ErrorData(
                    code=-32603,
                    message="internal_error: unknown approval decision type",
                    data={POLICY_GATEWAY_STAMP_KEY: True, "name": name, "decision_type": type(decision_obj).__name__},
                )
            )
        return None


def install_policy_gateway(
    comp: Any,
    *,
    hub: ApprovalHub,
    policy_reader: PolicyReaderStub,
    pending_notifier: Callable[[str, str, str | None], Awaitable[None]] | None = None,
    record_outcome: Callable[[str, str, ApprovalOutcome], Awaitable[None]] | None = None,
) -> PolicyGatewayMiddleware:
    """Install PolicyGatewayMiddleware on a FastMCP-like server.

    This mirrors production wiring in the container; tests should reuse this
    helper to avoid drift in middleware configuration.

    Returns the installed middleware instance for tracking in-flight calls.
    """
    middleware = PolicyGatewayMiddleware(
        hub=hub, pending_notifier=pending_notifier, record_outcome=record_outcome, policy_reader=policy_reader
    )
    comp.add_middleware(middleware)
    return middleware
