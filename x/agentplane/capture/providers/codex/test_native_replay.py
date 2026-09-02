"""Behavioral replay tests for the native Codex harness."""

from __future__ import annotations

import pytest_bazel

from x.agentplane.capture.providers.codex import replay_assertions as assertions, scenarios as codex

pytest_plugins = ("x.agentplane.capture.replay_fixtures", "x.agentplane.capture.providers.codex.replay_fixtures")


def test_codex_idle_resume_replays_through_the_pinned_native_cli(codex_replay, replay_server, captured_frames) -> None:
    with replay_server("codex", "idle_resume") as server:
        with codex_replay.capture(server) as first:
            handshake = codex.launch_handshake(
                first,
                cwd=str(codex_replay.root),
                model="chatgpt/oai-responses/gpt-5.6-luna",
                effort="low",
                persist=True,
            )
            seed = codex.submit(
                first,
                thread_start_response=handshake["thread_start_response"],
                text="Reply with exactly: IDLE_RESUME_SEED_OK",
            )
            assert assertions.result_text(seed) == "IDLE_RESUME_SEED_OK"
        with codex_replay.capture(server) as second:
            resumed = codex.resume_handshake(second, thread_id=seed["thread_id"])
            assert resumed["thread_resume_response"]["result"]["thread"]["id"] == seed["thread_id"]
            followup = codex.submit_to_thread(
                second, thread_id=seed["thread_id"], request_id="capture-6", text="Reply with exactly: IDLE_RESUME_OK"
            )
            assert assertions.result_text(followup) == "IDLE_RESUME_OK"
            server.assert_consumed()
            assertions.assert_request_shape(server)
            assertions.assert_prompt_is_capture_scoped(server)


def test_codex_baseline_replays_through_the_pinned_native_cli(codex_replay, replay_server, captured_frames) -> None:
    with replay_server("codex", "baseline") as server:
        with codex_replay.capture(server) as capture:
            handshake = codex.launch_handshake(
                capture, cwd=str(codex_replay.root), model="chatgpt/oai-responses/gpt-5.6-luna", effort="low"
            )
            submission = codex.baseline(capture, thread_start_response=handshake["thread_start_response"])
            assert assertions.result_text(submission) == "CAPTURE_BASELINE_OK"
            assert capture.process is not None
            assert capture.process.poll() is None
        frames = assertions.assert_success(codex_replay.root, "CAPTURE_BASELINE_OK")
        assert assertions.assert_item_lifecycles(frames, "userMessage")
        assertions.assert_request_shape(server)
        assertions.assert_prompt_is_capture_scoped(server)
        server.assert_consumed()


def test_codex_post_failure_follow_up_replays_through_the_pinned_native_cli(
    codex_replay, replay_server, captured_frames
) -> None:
    with replay_server("codex", "post_failure_follow_up") as server:
        with codex_replay.capture(server) as capture:
            handshake = codex.launch_handshake(
                capture, cwd=str(codex_replay.root), model="chatgpt/oai-responses/gpt-5.6-luna", effort="low"
            )
            partial = codex.submit(
                capture,
                thread_start_response=handshake["thread_start_response"],
                text="Reply with exactly: POST_FAILURE_FIRST_OK",
            )
            assert assertions.result_text(partial)
            assert capture.process is not None
            assert capture.process.poll() is None
            followup = codex.submit_to_thread(
                capture,
                thread_id=partial["thread_id"],
                request_id="capture-4",
                text="Reply with exactly: POST_FAILURE_FOLLOW_UP_OK",
            )
            assert assertions.result_text(followup)
        frames = assertions.assert_success(codex_replay.root, "POST_FAILURE_FOLLOW_UP_OK")
        assert sum(frame.get("method") == "error" for frame in frames) >= 1
        assert len(assertions.completed_turns(frames)) >= 2
        server.assert_consumed()


def test_codex_connection_retry_replays_through_the_pinned_native_cli(
    codex_replay, replay_server, captured_frames
) -> None:
    with replay_server("codex", "connection_retry") as server:
        with codex_replay.capture(server) as capture:
            handshake = codex.launch_handshake(
                capture, cwd=str(codex_replay.root), model="chatgpt/oai-responses/gpt-5.6-luna", effort="low"
            )
            retried = codex.submit(
                capture,
                thread_start_response=handshake["thread_start_response"],
                text="Reply with exactly: CONNECTION_RETRY_OK",
            )
            assert assertions.result_text(retried) == "CONNECTION_RETRY_OK"
            assert capture.process is not None
            assert capture.process.poll() is None
        frames = assertions.assert_success(codex_replay.root, "CONNECTION_RETRY_OK")
        errors = [frame for frame in frames if frame.get("method") == "error"]
        assert any(frame.get("params", {}).get("willRetry") is True for frame in errors)
        assert [text for text in assertions.agent_texts(frames) if text] == ["CONNECTION_RETRY_OK"]
        server.assert_consumed()


def test_codex_post_exhaustion_follow_up_replays_through_the_pinned_native_cli(
    codex_replay, replay_server, captured_frames
) -> None:
    with replay_server("codex", "post_exhaustion_follow_up") as server:
        with codex_replay.capture(server) as capture:
            handshake = codex.launch_handshake(
                capture, cwd=str(codex_replay.root), model="chatgpt/oai-responses/gpt-5.6-luna", effort="low"
            )
            failed = codex.submit(
                capture,
                thread_start_response=handshake["thread_start_response"],
                text="Reply with exactly: POST_EXHAUSTION_FIRST_OK",
            )
            assert failed["terminal"]["params"]["turn"]["status"] == "failed"
            followup = codex.submit_to_thread(
                capture,
                thread_id=failed["thread_id"],
                request_id="capture-4",
                text="Reply with exactly: POST_EXHAUSTION_FOLLOW_UP_OK",
            )
            assert assertions.result_text(followup) == "POST_EXHAUSTION_FOLLOW_UP_OK"
        frames = captured_frames()
        turns = assertions.completed_turns(frames)
        assert [turn["status"] for turn in turns[-2:]] == ["failed", "completed"]
        assert assertions.agent_texts(frames)[-1] == "POST_EXHAUSTION_FOLLOW_UP_OK"
        server.assert_consumed()


def test_codex_shell_replays_command_lifecycles_through_the_pinned_native_cli(
    codex_replay, replay_server, captured_frames
) -> None:
    with replay_server("codex", "shell") as server:
        with codex_replay.capture(server) as capture:
            handshake = codex.launch_handshake(
                capture, cwd=str(codex_replay.root), model="chatgpt/oai-responses/gpt-5.6-luna", effort="low"
            )
            submission = codex.submit(
                capture,
                thread_start_response=handshake["thread_start_response"],
                text="Use the shell probe and report its outcomes.",
            )
            assert assertions.result_text(submission)
            assert capture.process is not None
            assert capture.process.poll() is None
        frames = assertions.assert_success_contains(codex_replay.root, "probe stderr before failure")
        commands = assertions.assert_item_lifecycles(frames, "commandExecution")
        assert len(commands) >= 2
        assert any(item.get("status") == "completed" and item.get("exitCode") == 0 for item in commands)
        assert any(item.get("status") == "failed" and item.get("exitCode") == 23 for item in commands)
        assert any("PROBE_STDOUT" in item.get("aggregatedOutput", "") for item in commands)
        server.assert_consumed()


def test_codex_file_edits_replays_command_lifecycle_and_workspace_effect(
    codex_replay, replay_server, captured_frames
) -> None:
    editable = codex_replay.root / "editable.txt"
    editable.write_text("before\n")
    with replay_server("codex", "file_edits") as server:
        with codex_replay.capture(server) as capture:
            handshake = codex.launch_handshake(
                capture, cwd=str(codex_replay.root), model="chatgpt/oai-responses/gpt-5.6-luna", effort="low"
            )
            submission = codex.submit(
                capture,
                thread_start_response=handshake["thread_start_response"],
                text="Read editable.txt, change it to exactly `after\\n`, reread it, then reply FILE_EDIT_DONE.",
            )
            assert assertions.result_text(submission) == "FILE_EDIT_DONE"
        frames = assertions.assert_success(codex_replay.root, "FILE_EDIT_DONE")
        commands = assertions.assert_item_lifecycles(frames, "commandExecution")
        assert any("before" in item.get("aggregatedOutput", "") for item in commands)
        assert any("after" in item.get("aggregatedOutput", "") for item in commands)
        assert editable.read_text() == "after\n"
        server.assert_consumed()


def test_codex_steering_replays_active_turn_and_native_steer_response(
    codex_replay, replay_server, captured_frames
) -> None:
    with replay_server("codex", "steering") as server:
        with codex_replay.capture(server) as capture:
            handshake = codex.launch_handshake(
                capture, cwd=str(codex_replay.root), model="chatgpt/oai-responses/gpt-5.6-luna", effort="low"
            )
            submission = codex.submit_while_active(
                capture, thread_start_response=handshake["thread_start_response"], scenario="steering"
            )
            assert assertions.result_text(submission) == "wait_started\nwait_finished"
            assert submission["followup_response"].get("id") == "capture-4"
            assert capture.process is not None
            assert capture.process.poll() is None
        frames = assertions.assert_success(codex_replay.root, "wait_started\nwait_finished")
        assert any(frame.get("method") == "item/started" for frame in frames)
        assert any(frame.get("method") == "item/completed" for frame in frames)
        server.assert_consumed()


def test_codex_second_input_replays_after_an_active_turn(codex_replay, replay_server, captured_frames) -> None:
    with replay_server("codex", "second_input") as server:
        with codex_replay.capture(server) as capture:
            handshake = codex.launch_handshake(
                capture, cwd=str(codex_replay.root), model="chatgpt/oai-responses/gpt-5.6-luna", effort="low"
            )
            submission = codex.submit_while_active(
                capture, thread_start_response=handshake["thread_start_response"], scenario="second_input"
            )
            assert assertions.result_text(submission) == "SECOND_INPUT_OBSERVED"
        frames = assertions.assert_success(codex_replay.root, "SECOND_INPUT_OBSERVED")
        user_messages = assertions.assert_item_lifecycles(frames, "userMessage")
        assert len(user_messages) >= 2
        server.assert_consumed()


def test_codex_interrupt_replays_native_interrupt_and_terminal_state(
    codex_replay, replay_server, captured_frames
) -> None:
    with replay_server("codex", "interrupt") as server:
        with codex_replay.capture(server) as capture:
            handshake = codex.launch_handshake(
                capture, cwd=str(codex_replay.root), model="chatgpt/oai-responses/gpt-5.6-luna", effort="low"
            )
            submission = codex.interrupt(
                capture, thread_start_response=handshake["thread_start_response"], with_queued_input=False
            )
            assert submission["interrupt_response"]["id"] == "capture-5"
            assert capture.process is not None
            assert capture.process.poll() is None
        frames = captured_frames()
        turns = assertions.completed_turns(frames)
        assert turns[-1]["status"] == "interrupted"
        assert not assertions.agent_texts(frames)
        server.assert_consumed()


def test_codex_connection_exhaustion_replays_retry_exhaustion(codex_replay, replay_server, captured_frames) -> None:
    with replay_server("codex", "connection_exhaustion") as server:
        with codex_replay.capture(server) as capture:
            handshake = codex.launch_handshake(
                capture, cwd=str(codex_replay.root), model="chatgpt/oai-responses/gpt-5.6-luna", effort="low"
            )
            failed = codex.submit(
                capture,
                thread_start_response=handshake["thread_start_response"],
                text="Reply with exactly: CONNECTION_EXHAUSTION_OK",
            )
            assert failed["terminal"]["params"]["turn"]["status"] == "failed"
            assert capture.process is not None
            assert capture.process.poll() is None
        frames = captured_frames()
        errors = [frame for frame in frames if frame.get("method") == "error"]
        assert sum(frame.get("params", {}).get("willRetry") is True for frame in errors) == 5
        assert any(frame.get("params", {}).get("willRetry") is False for frame in errors)
        assert assertions.completed_turns(frames)[-1]["status"] == "failed"
        server.assert_consumed()


if __name__ == "__main__":
    pytest_bazel.main()
