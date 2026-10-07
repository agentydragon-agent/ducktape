"""A real app-server compaction must not drop thread-level standing instructions."""

from __future__ import annotations

import asyncio

import pytest_bazel

from agentplane.harness_tests.codex import responses_sse as sse
from agentplane.harness_tests.codex.harness import MODEL, CodexHarness
from agentplane.harness_tests.codex.responses import OpenAIResponses
from agentplane.native.codex import wire

STANDING = "AGENTPLANE_COMPACTION_STANDING_ORDER: check the inbox before answering."


async def test_compaction_preserves_instructions_in_next_request_and_resume(
    codex: CodexHarness, openai_responses: OpenAIResponses
) -> None:
    async with codex.start(openai_responses, persist=True, instructions=STANDING) as first:
        turn = await first.start_turn("Reply SEED_OK")
        async with await openai_responses.await_next_request() as exchange:
            assert [message.text for message in exchange.request.messages("developer")] == [STANDING]
            await exchange.send(*sse.response_stream([sse.Message("SEED_OK")], model=MODEL).events)
        assert (await turn.completed()).params.turn.status is wire.TurnStatus.COMPLETED

        # This RPC is not a model prompt. Require its native completion event before calling
        # the next request post-compaction; otherwise an ordinary second turn gives a false pass.
        events = first.events()
        compact = asyncio.create_task(first.compact())
        async with await openai_responses.await_next_request() as exchange:
            assert exchange.request.client_metadata.thread_id == first.thread_id
            await exchange.send(
                *sse.response_stream([sse.Message("Summary: seed turn completed.")], model=MODEL).events
            )
        assert (await compact).error is None
        while True:
            frame = await events.next()
            if isinstance(frame, wire.UnknownNotification) and frame.method == "thread/compacted":
                assert frame.params["threadId"] == first.thread_id
                break

        turn = await first.start_turn("Reply AFTER_COMPACT_OK")
        async with await openai_responses.await_next_request() as exchange:
            request = exchange.request
            assert request.client_metadata.turn_id == turn.id  # ordinary request, not the summary call
            assert request.messages("user")[-1].text == "Reply AFTER_COMPACT_OK"
            assert [message.text for message in request.messages("developer")] == [STANDING]
            await exchange.send(*sse.response_stream([sse.Message("AFTER_COMPACT_OK")], model=MODEL).events)
        assert (await turn.completed()).params.turn.status is wire.TurnStatus.COMPLETED

    async with codex.start(openai_responses, resume_thread_id=first.thread_id) as resumed:
        turn = await resumed.start_turn("Reply RESUMED_OK")
        async with await openai_responses.await_next_request() as exchange:
            assert exchange.request.client_metadata.turn_id == turn.id
            assert [message.text for message in exchange.request.messages("developer")] == [STANDING]
            await exchange.send(*sse.response_stream([sse.Message("RESUMED_OK")], model=MODEL).events)
        assert (await turn.completed()).params.turn.status is wire.TurnStatus.COMPLETED


if __name__ == "__main__":
    pytest_bazel.main()
