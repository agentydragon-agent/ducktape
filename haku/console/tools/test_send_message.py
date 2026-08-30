"""Contracts for the approval-gated ``workers.send_message`` action."""

from unittest.mock import AsyncMock
from uuid import UUID

import pytest_bazel
from fastmcp import Client

from haku.console.conversation.prompt_origin import SPA_ORIGIN
from haku.console.conversation_read_access import ConversationReadAccessPolicy
from haku.console.grants.principal import RequestPrincipal
from haku.console.mcp.execution import (
    AgentMcpExecutionCaller,
    McpExecutionContext,
    OperatorMcpExecutionCaller,
    mcp_execution_request_meta,
)
from haku.console.tool_call_actor import AgentActor, OperatorActor
from haku.console.tools.workers import build_mcp

_SESSION_ID = UUID("50000000-0000-4000-8000-00000000dd01")
_PROMPT_ID = UUID("50000000-0000-4000-8000-00000000dd02")
_OPERATOR_ID = UUID("50000000-0000-4000-8000-00000000dd03")
_AGENT_ID = UUID("50000000-0000-4000-8000-00000000dd04")


class _Sessions:
    def __init__(self, result: UUID | Exception = _PROMPT_ID):
        self.enqueue_prompt = AsyncMock(return_value=result if not isinstance(result, Exception) else None)
        if isinstance(result, Exception):
            self.enqueue_prompt.side_effect = result


def _meta(actor: AgentActor | OperatorActor, *, approving_operator_id: UUID | None = None) -> dict[str, object]:
    caller = (
        AgentMcpExecutionCaller(
            principal=RequestPrincipal(
                agent_id=actor.agent_id, session_id=actor.session_id, access_profile_id=actor.access_profile_id
            )
        )
        if isinstance(actor, AgentActor)
        else OperatorMcpExecutionCaller(operator_id=actor.operator_id)
    )
    return mcp_execution_request_meta(
        McpExecutionContext(
            caller=caller,
            tool_call_id="tc_test",
            approving_operator_id=approving_operator_id,
            approval_policy_id="manual" if approving_operator_id else None,
        )
    )


async def test_send_message_is_registered_with_bounded_text_schema() -> None:
    async with Client(build_mcp(_Sessions(), conversation_reads=ConversationReadAccessPolicy(()))) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
    assert "send_message" in tools
    schema = tools["send_message"].inputSchema
    assert schema["properties"]["text"]["minLength"] == 1
    assert schema["properties"]["text"]["maxLength"] == 100_000


async def test_agent_requires_per_call_operator_approval() -> None:
    sessions = _Sessions()
    actor = AgentActor(agent_id=_AGENT_ID, operator_id=_OPERATOR_ID, binding_id=UUID(int=5))
    async with Client(build_mcp(sessions, conversation_reads=ConversationReadAccessPolicy(()))) as client:
        result = await client.call_tool(
            "send_message",
            {"session_id": str(_SESSION_ID), "text": "continue the work"},
            meta=_meta(actor),
            raise_on_error=False,
        )
    assert result.is_error
    assert "per-call Operator approval" in str(result.content)
    sessions.enqueue_prompt.assert_not_awaited()


async def test_approved_agent_enqueues_user_role_prompt_and_returns_prompt_id() -> None:
    sessions = _Sessions()
    actor = AgentActor(agent_id=_AGENT_ID, operator_id=_OPERATOR_ID, binding_id=UUID(int=5))
    async with Client(build_mcp(sessions, conversation_reads=ConversationReadAccessPolicy(()))) as client:
        result = await client.call_tool(
            "send_message",
            {"session_id": str(_SESSION_ID), "text": "continue the work"},
            meta=_meta(actor, approving_operator_id=_OPERATOR_ID),
        )
    assert result.data.session_id == _SESSION_ID
    assert result.data.prompt_id == _PROMPT_ID
    sessions.enqueue_prompt.assert_awaited_once_with(_OPERATOR_ID, _SESSION_ID, "continue the work", SPA_ORIGIN)


async def test_operator_can_send_directly() -> None:
    async with Client(build_mcp(sessions, conversation_reads=ConversationReadAccessPolicy(()))) as client:
        result = await client.call_tool(
            "send_message",
            {"session_id": str(_SESSION_ID), "text": "operator follow-up"},
            meta=_meta(OperatorActor(operator_id=_OPERATOR_ID)),
        )
    assert result.data.prompt_id == _PROMPT_ID


async def test_unknown_session_is_reported() -> None:
    sessions = _Sessions(KeyError(_SESSION_ID))
    async with Client(build_mcp(sessions, conversation_reads=ConversationReadAccessPolicy(()))) as client:
        result = await client.call_tool(
            "send_message",
            {"session_id": str(_SESSION_ID), "text": "missing"},
            meta=_meta(OperatorActor(operator_id=_OPERATOR_ID)),
            raise_on_error=False,
        )
    assert result.is_error
    assert "session not found" in str(result.content)


if __name__ == "__main__":
    pytest_bazel.main()
