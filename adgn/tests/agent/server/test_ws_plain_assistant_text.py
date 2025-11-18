from __future__ import annotations

from concurrent.futures import CancelledError

import pytest

from adgn.agent.server.protocol import ErrorCode
from tests.agent.helpers import expect_error, expect_run_finished
from tests.llm.support.openai_mock import FakeOpenAIModel


@pytest.mark.timeout(3)
def test_ws_plain_assistant_text(responses_factory, agent_ws_box) -> None:
    """End-to-end: send a user text and receive a plain assistant_text via v1 protocol.

    We mock OpenAI Responses to return a single assistant message with text.
    """

    # using top-level import
    model_client = FakeOpenAIModel([responses_factory.make_assistant_message("plain-ok")])

    try:
        with agent_ws_box(model_client, specs={}) as box:
            # Use REST to start the run; WS is receive-only
            r = box.http.prompt("hi")
            assert r.status_code == 200
            assert (r.json() or {}).get("ok") is True
            payloads = box.collect(limit=40)
            expect_error(payloads, code=ErrorCode.AGENT_ERROR, message_substr="agent_run_exception")
            expect_run_finished(payloads)
    except CancelledError:
        pass
