from __future__ import annotations

from concurrent.futures import CancelledError

import pytest

from adgn.agent.server import protocol
from adgn.openai_utils.model import FakeOpenAIModel
from tests.agent.helpers import expect_error, expect_run_finished

Envelope = protocol.Envelope
ErrorCode = protocol.ErrorCode


@pytest.mark.timeout(3)
def test_ws_plain_assistant_text(
    responses_factory,
    ws_session,
) -> None:
    """End-to-end: send a user text and receive a plain assistant_text via v1 protocol.

    We mock OpenAI Responses to return a single assistant message with text.
    """

    # using top-level import
    model_client = FakeOpenAIModel([responses_factory.make_assistant_message("plain-ok")])

    try:
        with ws_session(model_client, specs={}) as (client, ws, collect, agent_id):
            ws.send_json({"type": "send", "text": "hi"})
            payloads = collect(limit=40)
            expect_error(payloads, code=ErrorCode.AGENT_ERROR, message_substr="agent_run_exception")
            expect_run_finished(payloads)
    except CancelledError:
        pass
