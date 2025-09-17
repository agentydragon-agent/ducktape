from __future__ import annotations

import asyncio
from concurrent.futures import CancelledError
from types import SimpleNamespace

from fastapi.testclient import TestClient

# OpenAI typed SDK classes used by MiniCodex
from openai.types.responses import ResponseOutputMessage, ResponseOutputText
import pytest

from adgn.llm.mini_codex.agent import MiniCodex
from adgn.llm.mini_codex.aggregating_handler import AutoHandler

# Use shared protocol definitions for envelope + payload (full union)
from adgn.llm.mini_codex.ui import protocol
from adgn.llm.mini_codex.ui.server import app, session

Envelope = protocol.Envelope
ServerMessage = protocol.ServerMessage


@pytest.mark.timeout(3)
def test_ws_plain_assistant_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end: send a user text and receive a plain assistant_text via v1 protocol.

    We mock OpenAI Responses to return a single assistant message with text.
    """

    async def fake_create(_client, **kwargs):
        usage = SimpleNamespace(input_tokens=1, output_tokens=1, total_tokens=2)
        msg = ResponseOutputMessage(
            id="msg_1",
            type="message",
            status="completed",
            role="assistant",
            content=[
                ResponseOutputText(type="output_text", text="plain-ok", annotations=[])
            ],
        )
        return SimpleNamespace(id="test-id", usage=usage, output=[msg])

    monkeypatch.setattr(
        "adgn.llm.mini_codex.agent._responses_create_with_retry",
        fake_create,
        raising=True,
    )

    # Minimal no-op MCP manager (no tools expected here)
    class DummyMcp:
        async def render_banner(self) -> str:  # pragma: no cover
            return ""

        async def list_tools(self):  # no tools in this test
            return []

    class DummyClient:
        @property
        def responses(self):  # pragma: no cover
            raise AssertionError(
                "responses.create should not be called directly in this test"
            )

    async def _mk_agent() -> MiniCodex:
        return await MiniCodex.create(
            model="test-model",
            mcp=DummyMcp(),
            system="You are a test agent.",
            client=DummyClient(),
            handlers=[AutoHandler()],
            parallel_tool_calls=False,
        )

    agent = asyncio.run(_mk_agent())
    session.attach_agent(agent)

    try:
        with TestClient(app) as client:
            with client.websocket_connect("/ws") as ws:
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
