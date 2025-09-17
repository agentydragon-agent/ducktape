from __future__ import annotations

import asyncio
from concurrent.futures import CancelledError
import logging
from types import SimpleNamespace

from fastapi.testclient import TestClient

# OpenAI typed SDK classes used by MiniCodex
from openai.types.responses import ResponseOutputMessage, ResponseOutputText
import pytest

from adgn.llm.logging_config import configure_logging
from adgn.llm.mini_codex.agent import MiniCodex
from adgn.llm.mini_codex.aggregating_handler import AutoHandler
from adgn.llm.mini_codex.mcp_manager import McpManager
from adgn.llm.mini_codex.ui.server import app, session


@pytest.mark.timeout(3)
def test_ui_websocket_roundtrip_with_mocked_openai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Spin up the real FastAPI app in-process, attach a MiniCodex agent with a mocked
    OpenAI Responses API call, then drive a websocket 'send' message and assert that
    an assistant_text event arrives back over the websocket.
    """

    # 1) Monkeypatch the OpenAI Responses call used by MiniCodex to avoid network.
    async def fake_create(
        _client,
        **kwargs,
    ):  # signature matches _responses_create_with_retry
        # Return a minimal object with .id, .usage, and .output containing a single
        # assistant message (no tool calls) so the agent returns promptly.
        usage = SimpleNamespace(input_tokens=1, output_tokens=1, total_tokens=2)
        msg = ResponseOutputMessage(
            id="msg_1",
            type="message",
            status="completed",
            role="assistant",
            content=[
                ResponseOutputText(type="output_text", text="pong", annotations=[]),
            ],
        )
        return SimpleNamespace(id="test-id", usage=usage, output=[msg])

    monkeypatch.setattr(
        "adgn.llm.mini_codex.agent._responses_create_with_retry",
        fake_create,
        raising=True,
    )

    # 2) Build a minimal dummy MCP manager that won't be used (no tool calls expected)
    class DummyMcp:
        async def render_banner(self) -> str:
            return ""

        async def list_tools(self):
            return []

        async def call_tool(
            self,
            server: str,
            tool: str,
            args: dict,
        ):  # pragma: no cover
            raise AssertionError("call_tool should not be invoked in this test")

    # 3) Construct the real agent synchronously via asyncio.run
    class DummyClient:
        @property
        def responses(
            self,
        ):  # pragma: no cover - never called because we monkeypatch the wrapper
            raise AssertionError(
                "responses.create should not be called directly in this test",
            )

    # Keep McpManager alive for the duration of the test (don't close early)
    mcp = McpManager({})
    asyncio.run(mcp.__aenter__())

    async def _mk_agent() -> MiniCodex:
        return await MiniCodex.create(
            model="test-model",
            mcp=mcp,
            system="You are a test agent.",
            client=DummyClient(),
            handlers=[AutoHandler()],
            parallel_tool_calls=False,
        )

    agent = asyncio.run(_mk_agent())

    # Attach agent to the UI session so websocket /ws can drive it
    session.attach_agent(agent)

    # 4) Configure logging for visibility in test, then drive the websocket protocol
    configure_logging()

    # Bump console handlers to INFO for this test and enable UI logger
    for h in logging.getLogger().handlers:
        if isinstance(h, logging.StreamHandler):
            h.setLevel(logging.INFO)
    logging.getLogger("mini_codex.ui").setLevel(logging.INFO)
    with TestClient(app) as client:
        try:
            with client.websocket_connect("/ws") as ws:
                # Send a user message
                ws.send_json({"type": "send", "text": "hi"})

                # Expect an immediate ack from server
                # Drain until we see the protocol ack (accepted); welcome/snapshot may arrive first
                seen = []
                first = None
                for _ in range(10):
                    m = ws.receive_json()
                    seen.append(m)
                    if m.get("type") == "accepted":
                        first = m
                        break
                if first is None:
                    raise AssertionError(f"accepted not received; got: {seen}")

                # Collect a few events until we see assistant_text
                received = [first]
                for _ in range(10):
                    msg = ws.receive_json()
                    received.append(msg)
                    if msg.get("type") == "assistant_text":
                        assert msg.get("text") == "pong"
                        break
                else:  # pragma: no cover - failure path
                    raise AssertionError(
                        f"assistant_text not received; got: {received}"
                    )
        except CancelledError:
            # Starlette TestClient may raise CancelledError on WS teardown; safe to ignore
            pass
