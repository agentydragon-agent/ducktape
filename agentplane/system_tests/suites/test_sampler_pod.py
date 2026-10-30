"""Executable sampler_pod scenarios sharing one k3s stack."""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_bazel

from agentplane.system_tests.executor import Executor
from agentplane.system_tests.scenarios import central_sampler
from agentplane.system_tests.scripted_upstream import ScriptedUpstream


@pytest.fixture
def executor() -> Executor:
    return Executor(template="runner", cwd="/state/workspaces/central-acceptance")


@pytest.fixture
def execution_probe() -> central_sampler.ExecutionProbe:
    return central_sampler.POD_EXECUTION


@pytest.mark.scripted_model
@pytest.mark.timeout(600)
async def test_dispatcher_central_setup_tool_and_retained_answer(
    tmp_path: Path, scripted: ScriptedUpstream, executor: Executor, execution_probe: central_sampler.ExecutionProbe
) -> None:
    await central_sampler.dispatcher_central_setup_tool_and_retained_answer(
        tmp_path, scripted, executor, execution_probe
    )


if __name__ == "__main__":
    pytest_bazel.main()
