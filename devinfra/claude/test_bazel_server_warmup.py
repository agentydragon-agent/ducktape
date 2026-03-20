"""Tests for bazel_server_warmup module."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import pytest_bazel

from devinfra.claude.bazel_server_warmup import BazelServerWarmup, _parse_info_output, warmup_bazel_server


def test_parse_info_output_success():
    output = "server_pid: 12345\noutput_base: /home/user/.cache/bazel/_bazel_root/abc123\n"
    result = _parse_info_output(output)
    assert result.server_pid == 12345
    assert result.output_base == Path("/home/user/.cache/bazel/_bazel_root/abc123")


def test_parse_info_output_empty():
    result = _parse_info_output("")
    assert result.server_pid is None
    assert result.output_base is None


def test_parse_info_output_partial():
    result = _parse_info_output("server_pid: 99\n")
    assert result.server_pid == 99
    assert result.output_base is None


async def test_warmup_success():
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"server_pid: 12345\noutput_base: /tmp/bazel\n", b""))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await warmup_bazel_server(
            wrapper_path=Path("/fake/bin/bazel"), project_dir=Path("/fake/project"), env={}
        )
    assert result == BazelServerWarmup(server_pid=12345, output_base=Path("/tmp/bazel"))


async def test_warmup_failure():
    mock_proc = AsyncMock()
    mock_proc.returncode = 1
    mock_proc.communicate = AsyncMock(return_value=(b"", b"ERROR: something\n"))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await warmup_bazel_server(
            wrapper_path=Path("/fake/bin/bazel"), project_dir=Path("/fake/project"), env={}
        )
    assert result == BazelServerWarmup()


async def test_warmup_timeout():
    mock_proc = AsyncMock()

    async def hang_forever():
        await asyncio.sleep(999)
        return (b"", b"")

    mock_proc.communicate = hang_forever

    with (
        patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        patch("devinfra.claude.bazel_server_warmup._WARMUP_TIMEOUT_SECS", 0.01),
        pytest.raises(TimeoutError),
    ):
        await warmup_bazel_server(wrapper_path=Path("/fake/bin/bazel"), project_dir=Path("/fake/project"), env={})


if __name__ == "__main__":
    pytest_bazel.main()
