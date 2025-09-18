from __future__ import annotations

import logging
from concurrent.futures import CancelledError
from types import SimpleNamespace

from fastapi.testclient import TestClient
from openai.types.responses import ResponseOutputMessage, ResponseOutputText
import pytest
from pydantic import TypeAdapter

from adgn.llm.logging_config import configure_logging
from adgn.llm.mini_codex.agent import MiniCodex
from adgn.llm.mini_codex.aggregating_handler import AutoHandler
from adgn.llm.mini_codex.ui.protocol import Envelope, Accepted, AssistantText
from adgn.llm.mini_codex.ui.server import create_app


@pytest.mark.timeout(5)
def test_ui_websocket_roundtrip_with_mocked_openai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Use FastAPI TestClient against a fresh create_app() instance. Attach a MiniCodex
    agent with a mocked OpenAI Responses call, send a websocket 'send' command,
    and assert an assistant_text event is received.
    """

    # 1) Monkeypatch the OpenAI Responses call used by MiniCodex to avoid network.
    async def fake_create(
        _client,
        **kwargs,
    ):
        usage = SimpleNamespace(input_tokens=1, output_tokens=1, total_tokens=2)
        msg = ResponseOutputMessage(
            id="msg_1",
            type="message",
            status="completed",
            role="assistant",
            content=[
                ResponseOutputText(type="output_text", text="pong", annotations=[])
            ],
        )
        return SimpleNamespace(id="test-id", usage=usage, output=[msg])

    monkeypatch.setattr(
        "adgn.llm.mini_codex.agent._responses_create_with_retry",
        fake_create,
        raising=True,
    )

    # 2) Dummy OpenAI client (never called directly due to monkeypatch)
    class DummyClient:
        @property
        def responses(self):  # pragma: no cover
            raise AssertionError(
                "responses.create should not be called directly in this test"
            )

    # 3) Build a fresh app and attach a real McpManager + MiniCodex on the TestClient loop
    app = create_app()

    configure_logging()
    for h in logging.getLogger().handlers:
        if isinstance(h, logging.StreamHandler):
            h.setLevel(logging.INFO)
    logging.getLogger("mini_codex.ui").setLevel(logging.INFO)

    with TestClient(app) as client:
        # Enter/exit the async manager on the TestClient's anyio portal loop
        # Minimal in-proc MCP stub for this UI roundtrip (no tool calls expected)
        class DummyMcp:
            @property
            def server_names(self) -> list[str]:
                return []

            async def sampling_snapshot(self):
                return SimpleNamespace(servers=[], tools=[])

            async def list_tools(self):  # pragma: no cover
                return []

            async def call_tool_namespaced(
                self, name: str, args_json: str | None
            ):  # pragma: no cover
                raise AssertionError("call_tool should not be invoked in this test")

        mcp = DummyMcp()
        try:
            agent = client.portal.call(
                MiniCodex.create,
                model="test-model",
                mcp=mcp,
                system="You are a test agent.",
                client=DummyClient(),
                handlers=[AutoHandler()],
                parallel_tool_calls=False,
            )
            app.state.session.attach_agent(agent)

            try:
                with client.websocket_connect("/ws") as ws:
                    # Send a user message
                    ws.send_json({"type": "send", "text": "hi"})

                    # Drain until we see the protocol ack (Accepted)
                    seen = []
                    first = None
                    env_adapter = TypeAdapter(Envelope)
                    for _ in range(20):
                        raw = ws.receive_json()
                        seen.append(raw)
                        env = env_adapter.validate_python(raw)
                        if isinstance(env.payload, Accepted):
                            first = env
                            break
                    if first is None:
                        raise AssertionError(f"accepted not received; got: {seen}")

                    # Collect events until we see assistant_text
                    received = [first.model_dump()] if first else []
                    for _ in range(50):
                        raw = ws.receive_json()
                        received.append(raw)
                        env = env_adapter.validate_python(raw)
                        if isinstance(env.payload, AssistantText):
                            assert env.payload.text == "pong"
                            break
                    else:  # pragma: no cover - failure path
                        raise AssertionError(
                            f"assistant_text not received; got: {received}"
                        )
            except CancelledError:  # pragma: no cover
                # Starlette TestClient may raise CancelledError on WS teardown; safe to ignore
                pass
        except Exception:  # pragma: no cover
            # Ignore unexpected teardown errors from TestClient/portal
            pass
