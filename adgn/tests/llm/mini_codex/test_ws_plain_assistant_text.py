from __future__ import annotations

import asyncio
from concurrent.futures import CancelledError

from fastapi.testclient import TestClient

# OpenAI typed helpers for Responses output
import pytest

from adgn.llm.mini_codex.agent import MiniCodex
from adgn.llm.mini_codex.aggregating_handler import AutoHandler

# Use shared protocol definitions for envelope + payload (full union)
from adgn.llm.mini_codex.ui import protocol
from adgn.llm.mini_codex.ui.server import create_app

Envelope = protocol.Envelope
ServerMessage = protocol.ServerMessage


@pytest.mark.timeout(3)
def test_ws_plain_assistant_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end: send a user text and receive a plain assistant_text via v1 protocol.

    We mock OpenAI Responses to return a single assistant message with text.
    """

    from adgn.llm.openai_utils.model import (
        FakeOpenAIModel,
        ResponsesResult,
        AssistantResponseMessage,
        Usage,
    )

    client = FakeOpenAIModel(
        [
            ResponsesResult(
                id="test",
                usage=Usage(input_tokens=0, output_tokens=1, total_tokens=1),
                output=[AssistantResponseMessage(text="plain-ok")],
            )
        ]
    )

    # Minimal no-op MCP manager (no tools expected here)
    class DummyMcp:
        async def render_banner(self) -> str:  # pragma: no cover
            return ""

        async def list_tools(self):  # no tools in this test
            return []

    async def _mk_agent() -> MiniCodex:
        return await MiniCodex.create(
            model="test-model",
            mcp=DummyMcp(),
            system="You are a test agent.",
            client=client,
            handlers=[AutoHandler()],
            parallel_tool_calls=False,
        )

    agent = asyncio.run(_mk_agent())
    app = create_app()
    app.state.session.attach_agent(agent)

    try:
        with TestClient(app) as client, client.websocket_connect("/ws") as ws:
            # Send a user message
            ws.send_json({"type": "send", "text": "hi"})

            # Drain until we see the protocol ack (accepted); welcome/snapshot may arrive first
            for _ in range(10):
                m = ws.receive_json()
                envelope = Envelope.model_validate(m)
                env = envelope.payload
                print(
                    "RECV:",
                    getattr(env, "type", None),
                    getattr(getattr(env, "run_state", None), "status", None),
                )
                if env.type == "accepted":
                    break
            else:
                raise AssertionError("accepted not received")

            # Expect an assistant_text and a finished run_status
            saw_text = False
            saw_finished = False
            for _ in range(20):
                m = ws.receive_json()
                envelope = Envelope.model_validate(m)
                env = envelope.payload
                print(
                    "RECV2:",
                    getattr(env, "type", None),
                    getattr(getattr(env, "run_state", None), "status", None),
                )
                if env.type == "assistant_text":
                    assert env.text == "plain-ok"
                    saw_text = True
                if (
                    env.type == "run_status"
                    and getattr(env, "run_state", None)
                    and getattr(env.run_state, "status", None) == "finished"
                ):
                    saw_finished = True
                    break
            assert saw_text, "assistant_text not received"
            assert saw_finished, "run_status finished not received"
    except CancelledError:
        pass
