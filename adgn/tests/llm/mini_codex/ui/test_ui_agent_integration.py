from __future__ import annotations

import asyncio
import json

import pytest
from adgn.llm.openai_utils.model import ResponsesResult, Usage, FunctionCallOut
from adgn.llm.mini_codex.agent import MiniCodex
from adgn.llm.mini_codex.ui.server import ConnectionManager, AgentSession
from adgn.llm.mini_codex.ui.ui_handler import UiAutoHandler
from adgn.llm.mini_codex.ui.shared_bus import UiBus
from adgn.llm.mini_codex.handler import ContinueDecision
from adgn.llm.mini_codex.mcp_manager import McpManager
from adgn.llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn.llm.mcp.ui.server import make_ui_mcp
from tests.llm.support.openai_mock import make_mock


def _make_ui_behavior():
    calls = {"n": 0}

    async def _behavior(req):
        calls["n"] += 1
        if calls["n"] == 1:
            args_json = json.dumps({"mime": "text/markdown", "content": "**hello**"})
            return ResponsesResult(
                id="resp_fc1",
                usage=Usage(input_tokens=0, output_tokens=0, total_tokens=0),
                output=[
                    FunctionCallOut(
                        name="mcp__ui__send_message",
                        call_id="call_1",
                        arguments=args_json,
                    )
                ],
            )
        return ResponsesResult(
            id="resp_fc2",
            usage=Usage(input_tokens=0, output_tokens=0, total_tokens=0),
            output=[
                FunctionCallOut(
                    name="mcp__ui__end_turn",
                    call_id="call_2",
                    arguments=json.dumps({}),
                )
            ],
        )

    return _behavior


@pytest.mark.asyncio
async def test_ui_server_with_mock_agent_produces_ui_state_updates():
    # Per-agent bus and UI MCP server
    bus = UiBus()
    ui_server = make_ui_mcp("ui", bus)
    specs = {"ui": make_inproc_slot_spec(ui_server)}

    captured: list[dict] = []

    mgr = ConnectionManager()
    sess = AgentSession(mgr)
    # Wire the per-agent bus so manager drains it on function outputs
    sess.ui_bus = bus  # type: ignore[attr-defined]

    # Patch send_json to capture envelopes
    orig_send_json = mgr.send_json

    async def _capture(payload: dict):
        captured.append(payload)
        # Auto-approve tool calls via the server's approval hub when running headless
        try:
            pl = payload.get("payload") if isinstance(payload, dict) else None
            if isinstance(pl, dict) and pl.get("type") == "approval_pending":
                call_id = pl.get("call_id") or ""
                # Defer resolution to avoid racing before_tool_call(await_decision)
                asyncio.get_running_loop().call_soon(
                    sess.approval_hub.resolve, call_id, ContinueDecision()
                )
        except Exception:
            # Tests should fail loudly elsewhere; keep capture non-fatal
            pass
        await orig_send_json(payload)

    mgr.send_json = _capture  # type: ignore[assignment]

    async with McpManager(specs) as mcp:
        handlers = [UiAutoHandler(bus=bus)]
        agent = await MiniCodex.create(
            model="test-model",
            mcp=mcp,
            handlers=handlers,
            client=make_mock(_make_ui_behavior()),
            system="Use ui tools",
        )
        sess.attach_agent(agent)

        # Kick off a run and wait for it to finish (end_turn triggers Abort)
        await sess.run("hello")
        # Wait for the background run task to complete
        if getattr(sess, "_task", None) is not None:
            await sess._task  # type: ignore[attr-defined]
        # Ensure any queued manager tasks are flushed and bus drained
        await mgr.flush()
        await mgr._emit_ui_bus_messages()  # type: ignore[attr-defined]

    # Verify directly on session state: AssistantMarkdown '**hello**' present
    items = sess.ui_state.items if hasattr(sess, "ui_state") else []  # type: ignore[attr-defined]
    assert any(
        getattr(it, "kind", None) == "AssistantMarkdown"
        and getattr(it, "md", None) == "**hello**"
        for it in items
    ), (
        f"expected AssistantMarkdown '**hello**' in UiState; got {[getattr(it, 'kind', None) for it in items]}"
    )
