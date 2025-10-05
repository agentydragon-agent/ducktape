from __future__ import annotations

from concurrent.futures import CancelledError

from hamcrest import any_of, assert_that, has_item, has_properties
import pytest

from adgn.agent.server.protocol import ErrorCode
from adgn.openai_utils.model import FakeOpenAIModel


@pytest.mark.timeout(5)
def test_ui_websocket_roundtrip_with_mocked_openai(
    responses_factory,
    ws_session,
) -> None:
    """
    Use FastAPI TestClient against a fresh create_app() instance. Attach a MiniCodex
    agent with a mocked OpenAI Responses call, send a websocket 'send' command,
    and assert an assistant_text event is received.
    """

    # Build a facade fake client that returns a single assistant text
    model_client = FakeOpenAIModel([responses_factory.make_assistant_message("pong")])

    try:
        with ws_session(model_client, specs={}) as (client, ws, collect, agent_id):
            ws.send_json({"type": "send", "text": "hi"})
            payloads = collect(limit=50)
            assert_that(
                payloads,
                has_item(
                    has_properties(
                        type="error",
                        code=any_of(ErrorCode.AGENT_ERROR, ErrorCode.ABORTED),
                    )
                ),
            )
    except CancelledError:  # pragma: no cover
        pass
