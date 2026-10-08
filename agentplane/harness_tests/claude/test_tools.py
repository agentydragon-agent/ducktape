"""Tool round trips: what the harness runs, what it reports back upstream, and workspace effects."""

from __future__ import annotations

import pytest_bazel

from agentplane.harness_tests.claude import anthropic_sse as sse, frames
from agentplane.harness_tests.claude.harness import MODEL, ClaudeHarness
from agentplane.harness_tests.claude.messages import AnthropicMessages

PROBE_FAILURE = (
    'sh -c \'printf "probe stdout before failure\\n"; printf "probe stderr before failure\\n" >&2; exit 23\''
)


async def test_parallel_shell_tools_report_both_streams_and_exit_codes(
    claude: ClaudeHarness, anthropic_messages: AnthropicMessages
) -> None:
    async with claude.start(anthropic_messages) as run:
        prompt = await run.send("Use the shell probe and report its outcomes.")

        async with await anthropic_messages.await_next_request() as exchange:
            stream = sse.message_stream(
                [
                    sse.Thinking("run both", "sig_test_1"),
                    sse.ToolUse("toolu_test_1", "Bash", {"command": "printf 'PROBE_STDOUT\\n'"}),
                    sse.ToolUse("toolu_test_2", "Bash", {"command": PROBE_FAILURE}),
                ],
                model=MODEL,
            )
            await exchange.send(*stream.events)

        async with await anthropic_messages.await_next_request() as exchange:
            request = exchange.request
            # The thinking block and its signature come back verbatim ahead of the tool uses.
            assert [(block.thinking, block.signature) for block in request.thinking_blocks] == [
                ("run both", "sig_test_1")
            ]
            assert [use.id for use in request.tool_uses] == ["toolu_test_1", "toolu_test_2"]
            first, second = request.tool_results
            assert first.tool_use_id == "toolu_test_1"
            assert first.text.startswith("PROBE_STDOUT")
            assert first.is_error is False
            assert second.tool_use_id == "toolu_test_2"
            assert "probe stdout before failure" in second.text
            assert "probe stderr before failure" in second.text
            assert "23" in second.text
            assert second.is_error is True
            stream = sse.message_stream([sse.Text("SHELL_PROBE_DONE")], model=MODEL)
            await exchange.send(*stream.events)

        assert (await prompt.result()).result == "SHELL_PROBE_DONE"
        assert run.running
    captured = run.native_frames()
    frames.assert_success(captured, "SHELL_PROBE_DONE")
    results = frames.assert_tool_lifecycles(captured, ["Bash", "Bash"])
    assert any("PROBE_STDOUT" in str(result) for result in results)
    assert any("probe stderr before failure" in str(result) and "23" in str(result) for result in results)


async def test_file_edit_round_trip_changes_the_workspace(
    claude: ClaudeHarness, anthropic_messages: AnthropicMessages
) -> None:
    editable = claude.workspace / "editable.txt"
    editable.write_text("before\n")
    path = str(editable)
    async with claude.start(anthropic_messages) as run:
        prompt = await run.send(
            "Read editable.txt, change it to exactly `after\\n`, reread it, then reply FILE_EDIT_DONE."
        )

        async with await anthropic_messages.await_next_request() as exchange:
            stream = sse.message_stream([sse.ToolUse("toolu_test_1", "Read", {"file_path": path})], model=MODEL)
            await exchange.send(*stream.events)

        async with await anthropic_messages.await_next_request() as exchange:
            (read_result,) = exchange.request.tool_results
            assert read_result.tool_use_id == "toolu_test_1"
            assert "before" in read_result.text
            stream = sse.message_stream(
                [
                    sse.ToolUse(
                        "toolu_test_2", "Edit", {"file_path": path, "old_string": "before", "new_string": "after"}
                    )
                ],
                model=MODEL,
            )
            await exchange.send(*stream.events)

        async with await anthropic_messages.await_next_request() as exchange:
            (edit_result,) = exchange.request.tool_results
            assert edit_result.tool_use_id == "toolu_test_2"
            assert edit_result.is_error is False
            assert editable.read_text() == "after\n"
            stream = sse.message_stream([sse.ToolUse("toolu_test_3", "Read", {"file_path": path})], model=MODEL)
            await exchange.send(*stream.events)

        async with await anthropic_messages.await_next_request() as exchange:
            (reread_result,) = exchange.request.tool_results
            assert reread_result.tool_use_id == "toolu_test_3"
            assert "after" in reread_result.text
            assert "before" not in reread_result.text
            stream = sse.message_stream([sse.Text("FILE_EDIT_DONE")], model=MODEL)
            await exchange.send(*stream.events)

        assert (await prompt.result()).result == "FILE_EDIT_DONE"
    captured = run.native_frames()
    frames.assert_success(captured, "FILE_EDIT_DONE")
    frames.assert_tool_lifecycles(captured, ["Read", "Edit", "Read"])


async def test_subagent_tool_frames_are_correlated_with_the_parent_call(
    claude: ClaudeHarness, anthropic_messages: AnthropicMessages
) -> None:
    """Drive a real foreground Agent, including its own tool round trip, without a live model."""
    async with claude.start(anthropic_messages, subagents=True) as run:
        prompt = await run.send("Delegate the shell probe to a child, then report its result.")

        async with await anthropic_messages.await_next_request() as exchange:
            assert "Agent" in exchange.request.tool_names
            stream = sse.message_stream(
                [
                    sse.ToolUse(
                        "toolu_spawn_child",
                        "Agent",
                        {
                            "description": "Child shell probe",
                            "subagent_type": "general-purpose",
                            "prompt": "Run the child shell probe and reply CHILD_DONE.",
                        },
                    )
                ],
                model=MODEL,
            )
            await exchange.send(*stream.events)

        async with await anthropic_messages.await_next_request() as exchange:
            # An actual child model request, not a parent-generated description of delegation.
            assert "Run the child shell probe" in "\n".join(exchange.request.texts("user"))
            assert not exchange.request.tool_results
            assert "Bash" in exchange.request.tool_names
            stream = sse.message_stream(
                [sse.ToolUse("toolu_child_shell", "Bash", {"command": "printf CHILD_TOOL_OUTPUT"})],
                model=MODEL,
            )
            await exchange.send(*stream.events)

        async with await anthropic_messages.await_next_request() as exchange:
            (result,) = exchange.request.tool_results
            assert result.tool_use_id == "toolu_child_shell"
            assert result.is_error is False
            assert "CHILD_TOOL_OUTPUT" in result.text
            stream = sse.message_stream([sse.Text("CHILD_DONE")], model=MODEL)
            await exchange.send(*stream.events)

        async with await anthropic_messages.await_next_request() as exchange:
            (result,) = exchange.request.tool_results
            assert result.tool_use_id == "toolu_spawn_child"
            assert result.is_error is False
            assert "CHILD_DONE" in result.text
            stream = sse.message_stream([sse.Text("PARENT_DONE")], model=MODEL)
            await exchange.send(*stream.events)

        assert (await prompt.result()).result == "PARENT_DONE"
        assert run.running

    captured = run.native_frames()
    frames.assert_success(captured, "PARENT_DONE")
    child_tool_frames = [
        frame
        for frame in captured
        if frame.get("type") == "assistant"
        and any(block.get("id") == "toolu_child_shell" for block in frame["message"]["content"])
    ]
    assert child_tool_frames
    assert {frame["parent_tool_use_id"] for frame in child_tool_frames} == {"toolu_spawn_child"}
    # Default forwarding exposes child tools, not the child's prose as a standalone assistant message.
    assert "CHILD_DONE" not in frames.assistant_texts(captured)


if __name__ == "__main__":
    pytest_bazel.main()
