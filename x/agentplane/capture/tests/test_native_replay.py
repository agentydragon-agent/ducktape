"""Hermetic native-harness replay tests against the recorded LiteLLM body scripts."""

from __future__ import annotations

import json
import os
import struct
import sys
from pathlib import Path
from typing import Any

import pytest_bazel

from util.bazel.runfiles import get_required_path
from x.agentplane.capture.providers.claude import scenarios as claude
from x.agentplane.capture.providers.codex import driver as codex_driver, scenarios as codex
from x.agentplane.capture.providers.shared_capture import NativeCapture
from x.agentplane.capture.replay import ReplayServer, serve

_LOGS = ("stdin.jsonl", "stdout.jsonl", "stderr.jsonl")


def _fixture(provider: str, scenario: str) -> Path:
    return get_required_path(f"{os.environ['TEST_WORKSPACE']}/x/agentplane/capture/testdata/{provider}/{scenario}")


def _capture(root: Path, command: list[str], environment: dict[str, str]) -> NativeCapture:
    output = root / "capture"
    output.mkdir(exist_ok=True)
    for name in _LOGS:
        (output / name).touch()
    return NativeCapture(output, command, cwd=root, environment=environment)


def _environment(root: Path, **overrides: str) -> dict[str, str]:
    home = root / "home"
    home.mkdir()
    return {"HOME": str(home), "NO_PROXY": "127.0.0.1,localhost", **overrides}


def _stderr(root: Path) -> str:
    records = (root / "capture" / "stderr.jsonl").read_text().splitlines()
    return "".join(json.loads(line)["text"] for line in records)


def _python_dynamic_loader() -> str:
    """Use the test interpreter's Nix-provided glibc loader for Claude's glibc ELF."""
    data = Path(sys.executable).resolve().read_bytes()
    if data[:4] != b"\x7fELF":
        raise RuntimeError("Bazel Python is not an ELF executable")
    program_offset = struct.unpack_from("<Q", data, 32)[0]
    program_size = struct.unpack_from("<H", data, 54)[0]
    program_count = struct.unpack_from("<H", data, 56)[0]
    for index in range(program_count):
        offset = program_offset + index * program_size
        if struct.unpack_from("<I", data, offset)[0] != 3:  # PT_INTERP
            continue
        interpreter_offset = struct.unpack_from("<Q", data, offset + 8)[0]
        interpreter_size = struct.unpack_from("<Q", data, offset + 32)[0]
        return data[interpreter_offset : interpreter_offset + interpreter_size].rstrip(b"\0").decode()
    raise RuntimeError("Bazel Python has no ELF interpreter")


def _claude_test_command(binary: str, *, resume_id: str | None = None) -> list[str]:
    """Keep the native stream protocol while avoiding Claude's root-only bypass guard in RBE."""
    command = claude.command(
        binary, model="anthropic-max20/ant-messages/claude-haiku-4-5-20251001", resume_id=resume_id
    )
    permission_mode = command.index("--permission-mode")
    del command[permission_mode : permission_mode + 2]
    return command


def _assert_request_shape(server: ReplayServer, *, model: str, protocol_key: str) -> None:
    assert server.observed
    body = json.loads(server.observed[0]["body"])
    assert body["model"] == model
    assert body["stream"] is True
    assert protocol_key in body


def _assert_small_claude_policy(server: ReplayServer) -> None:
    """The pinned CLI must not inherit host skills or broad project instructions."""
    for observed in server.observed:
        body = json.loads(observed["body"])
        for block in body.get("system", []):
            if isinstance(block, dict):
                assert len(block.get("text", "")) < 15_000


def _assert_codex_prompt_is_capture_scoped(server: ReplayServer) -> None:
    assert server.observed
    for observed in server.observed:
        body = json.loads(observed["body"])
        assert body["instructions"] == codex_driver.BASE_INSTRUCTIONS
        serialized = observed["body"].decode("utf-8")
        assert "<skills_instructions>" not in serialized
        assert "<permissions instructions>" not in serialized
        assert "<apps_instructions>" not in serialized
        assert "<collaboration_mode>" not in serialized
        assert "<environment_context>" not in serialized


def _claude_result_text(submission: dict[str, Any]) -> str:
    terminal = submission["terminal"]
    assert isinstance(terminal, dict)
    result = terminal.get("result")
    assert isinstance(result, str), terminal
    return result


def _codex_result_text(submission: dict[str, Any]) -> str:
    terminal = submission["terminal"]
    assert isinstance(terminal, dict)
    items = terminal["params"]["turn"]["items"]
    assert items, terminal
    text = items[-1]["text"]
    assert isinstance(text, str)
    return text


def test_claude_baseline_replays_through_the_pinned_native_cli(tmp_path: Path) -> None:
    fixture = _fixture("claude", "baseline")
    root = tmp_path
    config = root / ".claude"
    config.mkdir()
    with serve(ReplayServer(fixture)) as server:
        endpoint = f"http://127.0.0.1:{server.server_port}"
        with _capture(
            root,
            [
                _python_dynamic_loader(),
                *_claude_test_command(str(get_required_path("claude_code_cli_linux_x64/claude"))),
            ],
            _environment(
                root, ANTHROPIC_AUTH_TOKEN="test-key", ANTHROPIC_BASE_URL=endpoint, CLAUDE_CONFIG_DIR=str(config)
            ),
        ) as capture:
            try:
                claude.launch_handshake(capture)
            except TimeoutError as error:
                raise AssertionError(_stderr(root)) from error
            assert _claude_result_text(claude.baseline(capture)) == "CAPTURE_BASELINE_OK"
            server.assert_consumed()
            _assert_request_shape(
                server, model="anthropic-max20/ant-messages/claude-haiku-4-5-20251001", protocol_key="messages"
            )
            _assert_small_claude_policy(server)


def test_claude_idle_resume_replays_through_the_pinned_native_cli(tmp_path: Path) -> None:
    fixture = _fixture("claude", "idle_resume")
    root = tmp_path
    config = root / ".claude"
    config.mkdir()
    binary = str(get_required_path("claude_code_cli_linux_x64/claude"))
    with serve(ReplayServer(fixture)) as server:
        endpoint = f"http://127.0.0.1:{server.server_port}"
        environment = _environment(
            root, ANTHROPIC_AUTH_TOKEN="test-key", ANTHROPIC_BASE_URL=endpoint, CLAUDE_CONFIG_DIR=str(config)
        )
        with _capture(root, [_python_dynamic_loader(), *_claude_test_command(binary)], environment) as first:
            claude.launch_handshake(first)
            seed = claude.submit(first, "Reply with exactly: IDLE_RESUME_SEED_OK")
            assert _claude_result_text(seed) == "IDLE_RESUME_SEED_OK"
        with _capture(
            root,
            [_python_dynamic_loader(), *_claude_test_command(binary, resume_id=claude.session_id(seed))],
            environment,
        ) as second:
            claude.launch_handshake(second)
            followup = claude.submit(second, "Reply with exactly: IDLE_RESUME_OK")
            assert _claude_result_text(followup) == "IDLE_RESUME_OK"
            server.assert_consumed()
            _assert_request_shape(
                server, model="anthropic-max20/ant-messages/claude-haiku-4-5-20251001", protocol_key="messages"
            )
            _assert_small_claude_policy(server)


def test_claude_post_failure_follow_up_replays_through_the_pinned_native_cli(tmp_path: Path) -> None:
    fixture = _fixture("claude", "post_failure_follow_up")
    config = tmp_path / ".claude"
    config.mkdir()
    binary = str(get_required_path("claude_code_cli_linux_x64/claude"))
    with serve(ReplayServer(fixture)) as server:
        endpoint = f"http://127.0.0.1:{server.server_port}"
        environment = _environment(
            tmp_path, ANTHROPIC_AUTH_TOKEN="***", ANTHROPIC_BASE_URL=endpoint, CLAUDE_CONFIG_DIR=str(config)
        )
        with _capture(tmp_path, [_python_dynamic_loader(), *_claude_test_command(binary)], environment) as capture:
            claude.launch_handshake(capture)
            partial = claude.submit(capture, "Reply with exactly: POST_FAILURE_FIRST_OK")
            assert _claude_result_text(partial) == ""
            followup = claude.submit(capture, "Reply with exactly: POST_FAILURE_FOLLOW_UP_OK")
            assert _claude_result_text(followup)
        server.assert_consumed()
        assert len(server.observed) == 3


def test_claude_connection_retry_replays_through_the_pinned_native_cli(tmp_path: Path) -> None:
    fixture = _fixture("claude", "connection_retry")
    config = tmp_path / ".claude"
    config.mkdir()
    binary = str(get_required_path("claude_code_cli_linux_x64/claude"))
    with serve(ReplayServer(fixture)) as server:
        endpoint = f"http://127.0.0.1:{server.server_port}"
        environment = _environment(
            tmp_path, ANTHROPIC_AUTH_TOKEN="***", ANTHROPIC_BASE_URL=endpoint, CLAUDE_CONFIG_DIR=str(config)
        )
        with _capture(tmp_path, [_python_dynamic_loader(), *_claude_test_command(binary)], environment) as capture:
            claude.launch_handshake(capture)
            retried = claude.submit(capture, "Reply with exactly: CONNECTION_RETRY_OK")
            assert _claude_result_text(retried) == "CONNECTION_RETRY_OK"
        server.assert_consumed()
        assert len(server.observed) >= 2


def test_codex_idle_resume_replays_through_the_pinned_native_cli(tmp_path: Path) -> None:
    fixture = _fixture("codex", "idle_resume")
    root = tmp_path
    codex_home = root / ".codex"
    codex_home.mkdir()
    with serve(ReplayServer(fixture)) as server:
        endpoint = f"http://127.0.0.1:{server.server_port}"
        environment = _environment(
            root, CODEX_HOME=str(codex_home), OPENAI_API_KEY="test-key", OPENAI_BASE_URL=f"{endpoint}/v1"
        )
        command = codex.command(
            str(get_required_path("agentplane_codex_cli_linux_x64/bin/codex")), endpoint=f"{endpoint}/v1"
        )
        with _capture(root, command, environment) as first:
            handshake = codex.launch_handshake(
                first, cwd=str(root), model="chatgpt/oai-responses/gpt-5.6-luna", effort="low", persist=True
            )
            seed = codex.submit(
                first,
                thread_start_response=handshake["thread_start_response"],
                text="Reply with exactly: IDLE_RESUME_SEED_OK",
            )
            assert _codex_result_text(seed) == "IDLE_RESUME_SEED_OK"
        with _capture(root, command, environment) as second:
            resumed = codex.resume_handshake(second, thread_id=seed["thread_id"])
            assert resumed["thread_resume_response"]["result"]["thread"]["id"] == seed["thread_id"]
            followup = codex.submit_to_thread(
                second, thread_id=seed["thread_id"], request_id="capture-6", text="Reply with exactly: IDLE_RESUME_OK"
            )
            assert _codex_result_text(followup) == "IDLE_RESUME_OK"
            server.assert_consumed()
            _assert_request_shape(server, model="chatgpt/oai-responses/gpt-5.6-luna", protocol_key="input")
            _assert_codex_prompt_is_capture_scoped(server)


def test_codex_post_failure_follow_up_replays_through_the_pinned_native_cli(tmp_path: Path) -> None:
    fixture = _fixture("codex", "post_failure_follow_up")
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    with serve(ReplayServer(fixture)) as server:
        endpoint = f"http://127.0.0.1:{server.server_port}"
        environment = _environment(
            tmp_path, CODEX_HOME=str(codex_home), OPENAI_API_KEY="***", OPENAI_BASE_URL=f"{endpoint}/v1"
        )
        command = codex.command(
            str(get_required_path("agentplane_codex_cli_linux_x64/bin/codex")), endpoint=f"{endpoint}/v1"
        )
        with _capture(tmp_path, command, environment) as capture:
            handshake = codex.launch_handshake(
                capture, cwd=str(tmp_path), model="chatgpt/oai-responses/gpt-5.6-luna", effort="low"
            )
            partial = codex.submit(
                capture,
                thread_start_response=handshake["thread_start_response"],
                text="Reply with exactly: POST_FAILURE_FIRST_OK",
            )
            assert _codex_result_text(partial)
            followup = codex.submit_to_thread(
                capture,
                thread_id=partial["thread_id"],
                request_id="capture-4",
                text="Reply with exactly: POST_FAILURE_FOLLOW_UP_OK",
            )
            assert _codex_result_text(followup)
        # The fixture routes one partial-stream loss, its native retry, and the user follow-up.
        # Request bodies carry volatile provider metadata, so route consumption is the stable assertion.
        server.assert_consumed()
        assert len(server.observed) == 3


def test_codex_connection_retry_replays_through_the_pinned_native_cli(tmp_path: Path) -> None:
    fixture = _fixture("codex", "connection_retry")
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    with serve(ReplayServer(fixture)) as server:
        endpoint = f"http://127.0.0.1:{server.server_port}"
        environment = _environment(
            tmp_path, CODEX_HOME=str(codex_home), OPENAI_API_KEY="***", OPENAI_BASE_URL=f"{endpoint}/v1"
        )
        command = codex.command(
            str(get_required_path("agentplane_codex_cli_linux_x64/bin/codex")), endpoint=f"{endpoint}/v1"
        )
        with _capture(tmp_path, command, environment) as capture:
            handshake = codex.launch_handshake(
                capture, cwd=str(tmp_path), model="chatgpt/oai-responses/gpt-5.6-luna", effort="low"
            )
            retried = codex.submit(
                capture,
                thread_start_response=handshake["thread_start_response"],
                text="Reply with exactly: CONNECTION_RETRY_OK",
            )
            assert _codex_result_text(retried) == "CONNECTION_RETRY_OK"
        server.assert_consumed()
        assert len(server.observed) >= 2


def test_codex_post_exhaustion_follow_up_replays_through_the_pinned_native_cli(tmp_path: Path) -> None:
    fixture = _fixture("codex", "post_exhaustion_follow_up")
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    with serve(ReplayServer(fixture)) as server:
        endpoint = f"http://127.0.0.1:{server.server_port}"
        environment = _environment(
            tmp_path, CODEX_HOME=str(codex_home), OPENAI_API_KEY="***", OPENAI_BASE_URL=f"{endpoint}/v1"
        )
        command = codex.command(
            str(get_required_path("agentplane_codex_cli_linux_x64/bin/codex")), endpoint=f"{endpoint}/v1"
        )
        with _capture(tmp_path, command, environment) as capture:
            handshake = codex.launch_handshake(
                capture, cwd=str(tmp_path), model="chatgpt/oai-responses/gpt-5.6-luna", effort="low"
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
            assert _codex_result_text(followup) == "POST_EXHAUSTION_FOLLOW_UP_OK"
        server.assert_consumed()
        assert len(server.observed) == 27


if __name__ == "__main__":
    pytest_bazel.main()
