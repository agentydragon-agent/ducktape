"""Shared pytest fixtures for native capture replay tests."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import Any

import pytest

from util.bazel.runfiles import get_required_path
from x.agentplane.capture.providers.shared_capture import NativeCapture
from x.agentplane.capture.replay import ReplayServer, serve

_LOGS = ("stdin.jsonl", "stdout.jsonl", "stderr.jsonl")


@pytest.fixture
def replay_server() -> Callable[[str, str], AbstractContextManager[ReplayServer]]:
    @contextmanager
    def _server(provider: str, scenario: str) -> Iterator[ReplayServer]:
        fixture = get_required_path(
            f"{os.environ['TEST_WORKSPACE']}/x/agentplane/capture/testdata/{provider}/{scenario}"
        )
        with serve(ReplayServer(fixture)) as server:
            yield server

    return _server


@pytest.fixture
def capture_factory(tmp_path: Path) -> Callable[[list[str], dict[str, str]], NativeCapture]:
    output = tmp_path / "capture"
    output.mkdir()
    for name in _LOGS:
        (output / name).touch()

    def _capture(command: list[str], environment: dict[str, str]) -> NativeCapture:
        return NativeCapture(output, command, cwd=tmp_path, environment=environment)

    return _capture


@pytest.fixture
def environment_factory(tmp_path: Path) -> Callable[..., dict[str, str]]:
    home = tmp_path / "home"
    home.mkdir()

    def _environment(**overrides: str) -> dict[str, str]:
        return {"HOME": str(home), "NO_PROXY": "127.0.0.1,localhost", **overrides}

    return _environment


@pytest.fixture
def captured_frames(tmp_path: Path) -> Callable[[], list[dict[str, Any]]]:
    def _frames() -> list[dict[str, Any]]:
        records = (tmp_path / "capture" / "stdout.jsonl").read_text().splitlines()
        return [json.loads(json.loads(line)["text"]) for line in records]

    return _frames


@pytest.fixture
def captured_stderr(tmp_path: Path) -> Callable[[], str]:
    def _stderr() -> str:
        records = (tmp_path / "capture" / "stderr.jsonl").read_text().splitlines()
        return "".join(json.loads(line)["text"] for line in records)

    return _stderr
