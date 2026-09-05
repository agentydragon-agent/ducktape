"""The runner initialization RPC executes configured source once per stable app identity."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest_bazel

from x.agentplane.runner.client import RunnerClient
from x.agentplane.runner.config import RunnerConfig
from x.agentplane.runner.service import serve


async def test_initialize_executes_before_marking_the_identity_complete(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    server, runner, port = await serve(RunnerConfig(state_dir=state))
    client = RunnerClient(f"127.0.0.1:{port}")
    script = "mkdir -p workspaces\nprintf 'ready\\n' >> workspaces/public-coder-ready\n"
    key = hashlib.sha256(b"sandbox-preset:public-coder").hexdigest()
    try:
        first = await client.initialize(key, script)
        repeated = await client.initialize(key, "printf 'changed\\n' >> workspaces/public-coder-ready\n")
    finally:
        await client.close()
        await runner.stop()
        await server.stop(0)

    assert (first.executed, first.exit_code, first.stderr) == (True, 0, "")
    assert (repeated.executed, repeated.exit_code) == (False, 0)
    assert (state / "workspaces/public-coder-ready").read_text() == "ready\n"
    assert (state / "initializations" / key).read_text() == "completed\n"


async def test_failed_initialize_is_visible_and_may_be_retried(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    server, runner, port = await serve(RunnerConfig(state_dir=state))
    client = RunnerClient(f"127.0.0.1:{port}")
    script = "echo broken >&2\nexit 7\n"
    key = hashlib.sha256(script.encode()).hexdigest()
    try:
        first = await client.initialize(key, script)
        retried = await client.initialize(key, script)
    finally:
        await client.close()
        await runner.stop()
        await server.stop(0)

    assert (first.executed, first.exit_code, first.stderr) == (True, 7, "broken\n")
    assert (retried.executed, retried.exit_code) == (True, 7)
    assert not (state / "initializations" / key).exists()


if __name__ == "__main__":
    pytest_bazel.main()
