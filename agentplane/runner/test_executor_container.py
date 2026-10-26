"""Exercise Codex shell dispatch and recovery through a private companion container."""

from __future__ import annotations

import asyncio
import json
import shlex
import socket
import time
from collections.abc import Iterator
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
import pytest_bazel

from agentplane.proto import event_pb2, runner_pb2
from agentplane.runner.testing import events, launches
from agentplane.runner.testing.config import RunnerTestConfig
from agentplane.runner.testing.driver import RunnerDriver, SessionFollow
from agentplane.runner.testing.fixtures import ModelEndpoint
from agentplane.testing.scripted_model import ScriptedModel, ShellCall, Text
from third_party.containers import debian_slim
from util.bazel.runfiles import get_required_path
from util.oci import load_oci_image
from util.testing.container_logs import LoggedContainer

# The generated protocol stubs' own stub chain, which the mypy aspect resolves for direct deps.
# gazelle:include_dep @pypi//protobuf

pytestmark = pytest.mark.parametrize("harness", [runner_pb2.HARNESS_CODEX], ids=["codex"])


@dataclass(frozen=True)
class ExecutorCompanion:
    url: str
    socket: Path
    container: LoggedContainer


@dataclass(frozen=True)
class ExecutorStatus:
    generation: str
    owned: bool


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _inspect_executor(path: Path) -> ExecutorStatus:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(2)
        connection.connect(str(path))
        connection.sendall(b'{"operation":"inspect"}\n')
        response = bytearray()
        while not response.endswith(b"\n"):
            chunk = connection.recv(4096)
            if not chunk:
                raise ConnectionError("executor companion closed its inspect connection")
            response.extend(chunk)
    status = json.loads(response)
    return ExecutorStatus(generation=status["generation"], owned=status["owned"])


@pytest.fixture
def executor_companion(tmp_path: Path) -> Iterator[ExecutorCompanion]:
    load_oci_image(debian_slim.IMAGE)
    runner_binary = get_required_path(launches.RUNNER_BINARY).resolve()
    codex_binary = get_required_path(launches.CODEX_BINARY).resolve()
    socket_path = tmp_path / "executor.sock"
    url = f"ws://127.0.0.1:{_free_port()}"
    container = (
        LoggedContainer(debian_slim.IMAGE.tag, test_name="runner-executor-companion")
        .with_kwargs(network_mode="host", restart_policy={"Name": "always"}, mem_limit="512m", pids_limit=64)
        .with_volume_mapping(str(tmp_path), str(tmp_path), mode="rw")
        .with_volume_mapping(str(runner_binary), "/runner", mode="ro")
        .with_volume_mapping(str(codex_binary.parent.parent), "/opt/codex", mode="ro")
        .with_command(
            shlex.join(
                [
                    "/runner",
                    "--executor-container",
                    "--socket",
                    str(socket_path),
                    "--listen",
                    url,
                    "--binary",
                    "/opt/codex/bin/codex",
                ]
            )
        )
    )
    started = time.monotonic()
    with container:
        # Docker only applies restart policies after the container has been up for ten seconds.
        # Give this generation that time before deliberately killing its PID 1 below.
        while not socket_path.exists():
            if time.monotonic() - started > 10:
                raise TimeoutError("executor companion did not create its ownership socket")
            time.sleep(0.05)
        time.sleep(max(0, 10 - (time.monotonic() - started)))
        yield ExecutorCompanion(url=url, socket=socket_path, container=container)


@pytest.fixture
def config(
    harness: runner_pb2.Harness, endpoint: ModelEndpoint, tmp_path: Path, executor_companion: ExecutorCompanion
) -> RunnerTestConfig:
    runner_config = launches.config(
        harness,
        endpoint.origin,
        state_dir=tmp_path / "state",
        home=tmp_path / "home",
        codex_executor_url=executor_companion.url,
        codex_executor_socket=executor_companion.socket,
    )
    environment = {**runner_config.harness_environment, "PATH": "/usr/bin:/bin"}
    return replace(runner_config, harness_environment=environment)


async def _wait_for_owned_generation(path: Path, previous: str) -> ExecutorStatus:
    async with asyncio.timeout(30):
        while True:
            try:
                status = await asyncio.to_thread(_inspect_executor, path)
            except OSError:
                await asyncio.sleep(0.1)
                continue
            if status.generation != previous and status.owned:
                return status
            await asyncio.sleep(0.1)


def _wait_for_marker_line(path: Path, line: str) -> None:
    deadline = time.monotonic() + 10
    while line not in path.read_text().splitlines():
        if time.monotonic() >= deadline:
            raise TimeoutError(f"{line!r} was not written to {path}")
        time.sleep(0.05)


async def _codex_process(driver: RunnerDriver) -> runner_pb2.HarnessProcessStatus:
    runner = await driver.gateway.control.runner()
    status: runner_pb2.RunnerStatus = await runner.GetStatus(runner_pb2.GetStatusRequest())
    (process,) = status.processes
    assert process.harness == runner_pb2.HARNESS_CODEX
    return process


async def _reply_to_tool(
    model: ScriptedModel, session: SessionFollow, call_id: str, command: str, result_text: str, expected_output: str
) -> None:
    request = await model.request()
    await model.reply(request, ShellCall(call_id, command))
    result = await model.request()
    (output,) = result.tool_outputs
    assert output.call_id == call_id
    assert output.contains(expected_output)
    await model.reply(result, Text(result_text))
    done = await session.until(events.turn_completed)
    assert done.event.turn_completed.status == event_pb2.TURN_STATUS_COMPLETED


async def test_companion_namespace_restarts_without_restarting_codex_app_server(
    driver: RunnerDriver,
    model: ScriptedModel,
    spec: runner_pb2.SessionSpec,
    workspace: Path,
    executor_companion: ExecutorCompanion,
) -> None:
    session = await driver.attach("isolated-executor", spec=spec)
    marker = workspace / "executor-runs.txt"
    marker_arg = shlex.quote(str(marker))
    delayed_write = f"printf 'detached-started\\n' >> {marker_arg}; sleep 5; printf 'late\\n' >> {marker_arg}"
    first_command = (
        f"printf 'first:' >> {marker_arg}; cat /proc/1/comm >> {marker_arg}; "
        f"setsid sh -c {shlex.quote(delayed_write)} </dev/null >/dev/null 2>&1 & "
        "printf FIRST_TOOL_OK"
    )

    await session.submit_input("input-1", "Run the first shell tool and report its output.")
    await _reply_to_tool(model, session, "call-first", first_command, "FIRST_DONE", "FIRST_TOOL_OK")
    await asyncio.to_thread(_wait_for_marker_line, marker, "detached-started")
    initial_executor = await asyncio.to_thread(_inspect_executor, executor_companion.socket)
    assert initial_executor.owned
    initial_app_server = await _codex_process(driver)
    assert initial_app_server.HasField("pid")
    assert marker.read_text().splitlines() == ["first:runner", "detached-started"]

    # Killing PID 1 produces ownership EOF; Docker restarts the private PID namespace.
    await asyncio.to_thread(
        executor_companion.container.get_wrapped_container().exec_run, ["/bin/sh", "-c", "kill -KILL 1"]
    )
    restarted_executor = await _wait_for_owned_generation(executor_companion.socket, initial_executor.generation)
    await asyncio.sleep(5.5)
    assert marker.read_text().splitlines() == ["first:runner", "detached-started"]

    recovered_app_server = await _codex_process(driver)
    assert recovered_app_server.pid == initial_app_server.pid

    await session.submit_input("input-2", "Run a fresh shell tool and report its output.")
    await _reply_to_tool(
        model,
        session,
        "call-second",
        f"printf 'second\\n' >> {marker_arg}; printf SECOND_TOOL_OK",
        "SECOND_DONE",
        "SECOND_TOOL_OK",
    )
    assert restarted_executor.generation != initial_executor.generation
    assert marker.read_text().splitlines() == ["first:runner", "detached-started", "second"]


if __name__ == "__main__":
    pytest_bazel.main()
