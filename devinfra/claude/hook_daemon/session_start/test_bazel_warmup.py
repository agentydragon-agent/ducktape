"""Tests for bazel_warmup module."""

import stat
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_bazel

from devinfra.claude.hook_daemon.session_start.bazel_warmup import start_bazel_command, warmup_bazel_server


def _write_script(path: Path, body: str) -> Path:
    path.write_text(f"#!/bin/bash\n{body}\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


async def test_warmup_success(tmp_path: Path):
    env_file = tmp_path / "env"
    env_file.write_text("# empty\n")
    wrapper = _write_script(tmp_path / "bazel", "exit 0")

    await warmup_bazel_server(wrapper_path=wrapper, project_dir=tmp_path, env_file=env_file)


async def test_warmup_failure(tmp_path: Path):
    env_file = tmp_path / "env"
    env_file.write_text("# empty\n")
    wrapper = _write_script(tmp_path / "bazel", "echo 'ERROR: something' >&2; exit 1")

    with pytest.raises(RuntimeError, match="bazel info exited 1"):
        await warmup_bazel_server(wrapper_path=wrapper, project_dir=tmp_path, env_file=env_file)


async def test_warmup_timeout(tmp_path: Path):
    env_file = tmp_path / "env"
    env_file.write_text("# empty\n")
    wrapper = _write_script(tmp_path / "bazel", "sleep 30")

    with (
        patch("devinfra.claude.hook_daemon.session_start.bazel_warmup._WARMUP_TIMEOUT_SECS", 1),
        pytest.raises(TimeoutError),
    ):
        await warmup_bazel_server(wrapper_path=wrapper, project_dir=tmp_path, env_file=env_file)


async def test_start_bazel_command_success(tmp_path: Path):
    env_file = tmp_path / "env"
    env_file.write_text("# empty\n")
    wrapper = _write_script(tmp_path / "bazel", "exit 0")

    handle = await start_bazel_command(
        wrapper_path=wrapper, project_dir=tmp_path, env_file=env_file, command="query //..."
    )
    assert handle.pid > 0
    await handle.wait()


async def test_start_bazel_command_failure(tmp_path: Path):
    env_file = tmp_path / "env"
    env_file.write_text("# empty\n")
    wrapper = _write_script(tmp_path / "bazel", "echo 'ERROR: bad' >&2; exit 1")

    handle = await start_bazel_command(
        wrapper_path=wrapper, project_dir=tmp_path, env_file=env_file, command="query //..."
    )
    assert handle.pid > 0
    with pytest.raises(RuntimeError, match=r"bazel query //\.\.\. exited 1"):
        await handle.wait()


async def test_start_bazel_command_timeout(tmp_path: Path):
    env_file = tmp_path / "env"
    env_file.write_text("# empty\n")
    wrapper = _write_script(tmp_path / "bazel", "sleep 30")

    handle = await start_bazel_command(
        wrapper_path=wrapper, project_dir=tmp_path, env_file=env_file, command="query //...", timeout_secs=1
    )
    with pytest.raises(TimeoutError):
        await handle.wait()


if __name__ == "__main__":
    pytest_bazel.main()
