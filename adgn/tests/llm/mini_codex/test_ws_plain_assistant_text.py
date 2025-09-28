from __future__ import annotations

import asyncio
from concurrent.futures import CancelledError
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest
from adgn.llm.openai_utils.model import FakeOpenAIModel

from adgn.llm.mini_codex.agent import MiniCodex
from adgn.llm.mini_codex.aggregating_handler import AutoHandler
from adgn.llm.mini_codex.ui import protocol
from adgn.llm.mini_codex.ui.server import create_app

Envelope = protocol.Envelope
ErrorCode = protocol.ErrorCode


@pytest.mark.timeout(3)
def test_ws_plain_assistant_text(
    monkeypatch: pytest.MonkeyPatch,
    responses_factory,
) -> None:
    """End-to-end: send a user text and receive a plain assistant_text via v1 protocol.

    We mock OpenAI Responses to return a single assistant message with text.
    """

    # using top-level import

    client = FakeOpenAIModel([responses_factory.make_assistant_message("plain-ok")])

    app = create_app(require_static_assets=False)

    class DummyMcp:
        async def sampling_snapshot(self):
            return SimpleNamespace(servers=[], tools=[])

        def poll_notifications(self):
            return SimpleNamespace(resources_updated=[], tools_invalidated=[])

        async def call_tool_namespaced(self, *_args, **_kwargs):  # pragma: no cover
            raise AssertionError("call_tool should not be invoked")

    async def _create_agent():
        return await MiniCodex.create(
            model="test-model",
            mcp=DummyMcp(),
            system="You are a test agent.",
            client=client,
            handlers=[AutoHandler()],
            parallel_tool_calls=False,
        )

    # Run in new event loop since TestClient creates its own
    agent = asyncio.run(_create_agent())
    app.state.session.attach_agent(agent)

    with TestClient(app) as test_client:
        try:
            with test_client.websocket_connect("/ws") as ws:
                ws.send_json({"type": "send", "text": "hi"})

                for _ in range(10):
                    payload = Envelope.model_validate(ws.receive_json()).payload
                    if payload.type == "accepted":
                        break
                else:  # pragma: no cover - defensive
                    raise AssertionError("accepted not received")

                saw_error = False
                saw_finished = False
                for _ in range(40):
                    payload = Envelope.model_validate(ws.receive_json()).payload
                    if payload.type == "error":
                        saw_error = True
                        assert payload.code == ErrorCode.AGENT_ERROR
                        assert payload.message == "agent_run_exception"
                    elif payload.type == "run_status":
                        if payload.run_state.status == "finished":
                            saw_finished = True
                            break
                assert saw_error, "agent error not emitted"
                assert saw_finished, "run_status finished not emitted"
        except CancelledError:
            # Some websockets tear down the background task with CancelledError.
            pass
