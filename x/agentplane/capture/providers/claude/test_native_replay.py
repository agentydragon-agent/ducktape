"""Behavioral replay tests for the native Claude harness."""

from __future__ import annotations

import pytest_bazel

from x.agentplane.capture.providers.claude import replay_assertions as assertions, scenarios as claude

pytest_plugins = ("x.agentplane.capture.replay_fixtures", "x.agentplane.capture.providers.claude.replay_fixtures")


def test_claude_baseline_replays_through_the_pinned_native_cli(
    claude_replay, replay_server, captured_frames, captured_stderr
) -> None:
    with replay_server("claude", "baseline") as server, claude_replay.capture(server) as capture:
        try:
            claude.launch_handshake(capture)
        except TimeoutError as error:
            raise AssertionError(captured_stderr()) from error
        assert assertions.result_text(claude.baseline(capture)) == "CAPTURE_BASELINE_OK"
        server.assert_consumed()
        assertions.assert_request_shape(server)
        assertions.assert_small_policy(server)


def test_claude_idle_resume_replays_through_the_pinned_native_cli(
    claude_replay, replay_server, captured_frames, captured_stderr
) -> None:
    with replay_server("claude", "idle_resume") as server:
        with claude_replay.capture(server) as first:
            claude.launch_handshake(first)
            seed = claude.submit(first, "Reply with exactly: IDLE_RESUME_SEED_OK")
            assert assertions.result_text(seed) == "IDLE_RESUME_SEED_OK"
        with claude_replay.capture(server, resume_id=claude.session_id(seed)) as second:
            claude.launch_handshake(second)
            followup = claude.submit(second, "Reply with exactly: IDLE_RESUME_OK")
            assert assertions.result_text(followup) == "IDLE_RESUME_OK"
            server.assert_consumed()
            assertions.assert_request_shape(server)
            assertions.assert_small_policy(server)


def test_claude_post_failure_follow_up_replays_through_the_pinned_native_cli(
    claude_replay, replay_server, captured_frames, captured_stderr
) -> None:
    with replay_server("claude", "post_failure_follow_up") as server:
        with claude_replay.capture(server) as capture:
            claude.launch_handshake(capture)
            partial = claude.submit(capture, "Reply with exactly: POST_FAILURE_FIRST_OK")
            assert assertions.result_text(partial) == ""
            assert capture.process is not None
            assert capture.process.poll() is None
            followup = claude.submit(capture, "Reply with exactly: POST_FAILURE_FOLLOW_UP_OK")
            assert assertions.result_text(followup)
        frames = captured_frames()
        terminals = [frame for frame in frames if frame.get("type") == "result"]
        assert [terminal["is_error"] for terminal in terminals[-2:]] == [False, False]
        assert any("POST_FAILURE_FIRST_OK" in text for text in assertions.assistant_texts(frames))
        assert any("POST_FAILURE_FOLLOW_UP_OK" in text for text in assertions.assistant_texts(frames))
        server.assert_consumed()


def test_claude_connection_retry_replays_through_the_pinned_native_cli(
    claude_replay, replay_server, captured_frames, captured_stderr
) -> None:
    with replay_server("claude", "connection_retry") as server:
        with claude_replay.capture(server) as capture:
            claude.launch_handshake(capture)
            retried = claude.submit(capture, "Reply with exactly: CONNECTION_RETRY_OK")
            assert assertions.result_text(retried) == "CONNECTION_RETRY_OK"
            assert capture.process is not None
            assert capture.process.poll() is None
        frames = assertions.assert_success(claude_replay.root, "CONNECTION_RETRY_OK")
        assert len(assertions.assistant_texts(frames)) == 1
        assertions.assert_request_shape(server)
        server.assert_consumed()


def test_claude_shell_replays_tool_lifecycle_through_the_pinned_native_cli(
    claude_replay, replay_server, captured_frames, captured_stderr
) -> None:
    with replay_server("claude", "shell") as server:
        with claude_replay.capture(server) as capture:
            claude.launch_handshake(capture)
            submission = claude.submit(capture, "Use the shell probe and report its outcomes.")
            assert assertions.result_text(submission)
            assert capture.process is not None
            assert capture.process.poll() is None
        frames = assertions.assert_success_contains(
            claude_replay.root,
            "Both stdout and stderr were captured even though the second command exited with a non-zero code.",
        )
        results = assertions.assert_tool_lifecycles(frames, ["Bash", "Bash"])
        assert any("PROBE_STDOUT" in str(result) for result in results)
        assert any("probe stderr before failure" in str(result) and "23" in str(result) for result in results)
        server.assert_consumed()


def test_claude_file_edits_replays_tool_lifecycle_and_workspace_effect(
    claude_replay, replay_server, captured_frames
) -> None:
    editable = claude_replay.root / "editable.txt"
    editable.write_text("before\n")
    try:
        with replay_server("claude", "file_edits") as server:
            with claude_replay.capture(server) as capture:
                claude.launch_handshake(capture)
                submission = claude.submit(capture, "Read editable.txt, change it to exactly `after\n`.")
                assert assertions.result_text(submission) == "FILE_EDIT_DONE"
            frames = assertions.assert_success(claude_replay.root, "FILE_EDIT_DONE")
            results = assertions.assert_tool_lifecycles(frames, ["Read", "Edit", "Read"])
            assert any(
                isinstance(result, dict) and result.get("file", {}).get("content") == "before\n" for result in results
            )
            assert any(
                isinstance(result, dict) and result.get("file", {}).get("content") == "after\n" for result in results
            )
            assert editable.read_text() == "after\n"
            server.assert_consumed()
    finally:
        editable.unlink(missing_ok=True)


def test_claude_steering_replays_the_provider_observed_active_turn_behavior(
    claude_replay, replay_server, captured_frames, captured_stderr
) -> None:
    with replay_server("claude", "steering") as server:
        with claude_replay.capture(server) as capture:
            claude.launch_handshake(capture)
            submission = claude.submit_while_active(capture, scenario="steering")
            assert assertions.result_text(submission) == "SECOND_INPUT_OBSERVED"
            assert capture.process is not None
            assert capture.process.poll() is None
        frames = assertions.assert_success(claude_replay.root, "SECOND_INPUT_OBSERVED")
        assert submission["first_uuid"] != submission["second_uuid"]
        assert submission["active_evidence"]["type"] == "stream_event"
        assert len([frame for frame in frames if frame.get("type") == "user"]) >= 2
        server.assert_consumed()


def test_claude_second_input_replays_after_an_active_turn(
    claude_replay, replay_server, captured_frames, captured_stderr
) -> None:
    with replay_server("claude", "second_input") as server:
        with claude_replay.capture(server) as capture:
            claude.launch_handshake(capture)
            submission = claude.submit_while_active(capture, scenario="second_input")
            assert assertions.result_text(submission) == "SECOND_INPUT_OBSERVED"
        frames = assertions.assert_success(claude_replay.root, "SECOND_INPUT_OBSERVED")
        assert len([frame for frame in frames if frame.get("type") == "user"]) >= 2
        server.assert_consumed()


def test_claude_interrupt_replays_native_abort_and_keeps_process_usable(
    claude_replay, replay_server, captured_frames, captured_stderr
) -> None:
    with replay_server("claude", "interrupt") as server:
        with claude_replay.capture(server) as capture:
            claude.launch_handshake(capture)
            submission = claude.interrupt(capture, with_queued_input=False)
            assert submission["interrupt_response"]["response"]["subtype"] == "success"
            assert capture.process is not None
            assert capture.process.poll() is None
        frames = assertions.assert_failure(claude_replay.root, result_fragment="", terminal_reason="aborted_streaming")
        assert not assertions.tool_uses(frames)
        server.assert_consumed()


def test_claude_connection_exhaustion_replays_native_retry_exhaustion(
    claude_replay, replay_server, captured_frames, captured_stderr
) -> None:
    with replay_server("claude", "connection_exhaustion") as server:
        with claude_replay.capture(server) as capture:
            claude.launch_handshake(capture)
            submission = claude.submit(capture, "Reply with exactly: CONNECTION_EXHAUSTION_OK")
            assert assertions.result_text(submission) == "API Error: Connection dropped (ECONNRESET)"
            assert capture.process is not None
            assert capture.process.poll() is None
        frames = assertions.assert_failure(
            claude_replay.root, result_fragment="Connection dropped (ECONNRESET)", terminal_reason="api_error"
        )
        retry_attempts = [frame for frame in frames if frame.get("type") == "system" and "attempt" in frame]
        assert retry_attempts
        server.assert_consumed()


def test_claude_post_exhaustion_follow_up_replays_same_process_recovery(
    claude_replay, replay_server, captured_frames, captured_stderr
) -> None:
    with replay_server("claude", "post_exhaustion_follow_up") as server:
        with claude_replay.capture(server) as capture:
            claude.launch_handshake(capture)
            failed = claude.submit(capture, "Reply with exactly: POST_EXHAUSTION_FIRST_OK")
            assert failed["terminal"]["is_error"] is True
            assert capture.process is not None
            assert capture.process.poll() is None
            followup = claude.submit(capture, "Reply with exactly: POST_EXHAUSTION_FOLLOW_UP_OK")
            assert assertions.result_text(followup) == "POST_EXHAUSTION_FOLLOW_UP_OK"
        frames = assertions.assert_success(claude_replay.root, "POST_EXHAUSTION_FOLLOW_UP_OK")
        terminals = [frame for frame in frames if frame.get("type") == "result"]
        assert [terminal["is_error"] for terminal in terminals[-2:]] == [True, False]
        server.assert_consumed()


if __name__ == "__main__":
    pytest_bazel.main()
