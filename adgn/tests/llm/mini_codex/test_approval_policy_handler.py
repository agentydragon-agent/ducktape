from __future__ import annotations

import asyncio
import json
import pytest

from adgn.llm.mini_codex.approvals import (
    ApprovalPolicyHandler,
    ApprovalHub,
)
from adgn.llm.mini_codex.handler import (
    ContinueDecision,
    AbortTurnDecision,
    BypassToolInjectOutput,
    ToolCall,
)
from adgn.llm.mini_codex.mcp_manager import build_mcp_function


@pytest.mark.asyncio
async def test_allow_ui_send_message_defaults_to_continue(approval_handler):
    decision = await approval_handler.before_tool_call(
        ToolCall(
            name=build_mcp_function("ui", "send_message"),
            args_json=json.dumps({"content": "hi"}),
            call_id="call_1",
        )
    )
    assert isinstance(decision, ContinueDecision)


@pytest.mark.asyncio
async def test_deny_continue_injects_bypass_result(approval_engine, approval_handler):
    # Deny for demo.foo
    approval_engine.set_policy(
        """
def decide(ctx: dict) -> str:
    if ctx.get("tool_key") == "mcp__demo__foo":
        return "deny_continue"
    return "ask"
"""
    )

    decision = await approval_handler.before_tool_call(
        ToolCall(
            name="mcp__demo__foo",
            args_json=json.dumps({"x": 1}),
            call_id="call_2",
        )
    )
    assert isinstance(decision, BypassToolInjectOutput)
    # Structured content should describe policy denial
    assert decision.result.isError is True
    assert isinstance(decision.result.structuredContent, dict)
    assert "policy denied" in json.dumps(decision.result.structuredContent)


@pytest.mark.asyncio
async def test_ask_path_blocks_until_hub_resolves(approval_engine):
    # Always ask for demo.bar
    approval_engine.set_policy(
        """
def decide(ctx: dict) -> str:
    if ctx.get("tool_key") == "mcp__demo__bar":
        return "ask"
    return "allow"
"""
    )
    hub = ApprovalHub()
    approval_handler = ApprovalPolicyHandler(approval_engine, hub)

    call_id = "call_3"

    # Start the await in background, then resolve via the hub
    task = asyncio.create_task(
        approval_handler.before_tool_call(
            ToolCall(name="mcp__demo__bar", args_json=json.dumps({}), call_id=call_id)
        )
    )
    # Let the handler enqueue the approval request
    await asyncio.sleep(0)
    hub.resolve(call_id, ContinueDecision())
    assert isinstance(await task, ContinueDecision)


@pytest.mark.asyncio
async def test_deny_abort_aborts_turn(approval_engine):
    approval_engine.set_policy(
        """
def decide(ctx: dict) -> str:
    return "deny_abort"
"""
    )
    hub = ApprovalHub()
    h = ApprovalPolicyHandler(approval_engine, hub)

    decision = await h.before_tool_call(
        ToolCall(name="mcp__demo__baz", args_json=json.dumps({}), call_id="call_4")
    )
    assert isinstance(decision, AbortTurnDecision)
