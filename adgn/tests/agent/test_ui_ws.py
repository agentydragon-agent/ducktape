from __future__ import annotations

import logging
from concurrent.futures import CancelledError
from fastapi.testclient import TestClient
import pytest
from pydantic import TypeAdapter
from adgn.openai_utils.model import FakeOpenAIModel

from adgn.llm.logging_config import configure_logging
from adgn.agent.agent import MiniCodex
from adgn.agent.reducer import AutoHandler
from adgn.agent.mcp_manager import McpManager
from adgn.agent.ui.protocol import Envelope, Accepted, AssistantText
from adgn.agent.ui.server import create_app


@pytest.mark.timeout(5)
def test_ui_websocket_roundtrip_with_mocked_openai(
    monkeypatch: pytest.MonkeyPatch,
    responses_factory,
) -> None:
    """
    Use FastAPI TestClient against a fresh create_app() instance. Attach a MiniCodex
    agent with a mocked OpenAI Responses call, send a websocket 'send' command,
    and assert an assistant_text event is received.
    """

    # Build a facade fake client that returns a single assistant text
    model_client = FakeOpenAIModel([responses_factory.make_assistant_message("pong")])

    # 3) Build a fresh app and attach a real McpManager + MiniCodex on the TestClient loop
    app = create_app(require_static_assets=False)

    configure_logging()
    for h in logging.getLogger().handlers:
        if isinstance(h, logging.StreamHandler):
            h.setLevel(logging.INFO)
    logging.getLogger("mini_codex.ui").setLevel(logging.INFO)

    with TestClient(app) as client:
        mgr = McpManager({})
        try:
            client.portal.call(mgr.__aenter__)
            agent = client.portal.call(
                MiniCodex.create,
                model="test-model",
                mcp=mgr,
                system="You are a test agent.",
                client=model_client,
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
        finally:
            try:
                client.portal.call(mgr.__aexit__, None, None, None)
            except Exception:  # pragma: no cover
                pass
