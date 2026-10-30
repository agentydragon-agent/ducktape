"""Suite-selected executor configuration and platform-specific execution checks."""

from collections.abc import Callable
from dataclasses import dataclass, replace

import pytest

from agentplane.system_tests.agent import WORKING_DIRECTORY
from agentplane.system_tests.conftest import POD_TEMPLATE, VM_TEMPLATE, VM_WORKING_DIRECTORY


def _verify_pod_executor(output: str) -> None:
    assert "prepared-on-executor\n" in output
    assert "tool-on-executor\n" in output
    assert "CENTRAL_EXECUTOR_OK\n" in output


def _verify_vm_executor(output: str) -> dict[str, str | int]:
    assert "prepared-on-executor\n" in output
    assert "VM_PID1 systemd\n" in output
    assert "VM_EXECUTOR_UID 107\n" in output
    (cgroup_line,) = [line for line in output.splitlines() if line.startswith("VM_EXECUTOR_CGROUP ")]
    executor_cgroup = cgroup_line.removeprefix("VM_EXECUTOR_CGROUP ")
    assert executor_cgroup.startswith("/agentplane.slice/agentplane-executors.slice/agentplane-native-"), (
        executor_cgroup
    )
    assert executor_cgroup.count("/") == 3, executor_cgroup
    assert executor_cgroup.endswith(".service"), executor_cgroup
    return {"pid1": "systemd", "uid": 107, "executor_cgroup": executor_cgroup}


@dataclass(frozen=True)
class ExecutorEnvironment:
    template: str
    cwd: str
    storage_case: str
    workspace_dir: str
    storage_cwd: str
    vm: bool
    sampler_probe: str
    verify_sampler_output: Callable[[str], dict[str, str | int] | None]


@pytest.fixture
def pod_executor() -> ExecutorEnvironment:
    return ExecutorEnvironment(
        template=POD_TEMPLATE,
        cwd=WORKING_DIRECTORY,
        storage_case="pod-directory",
        workspace_dir="/workspace",
        storage_cwd="/workspace",
        vm=False,
        sampler_probe="",
        verify_sampler_output=_verify_pod_executor,
    )


@pytest.fixture
def sampler_pod_executor(pod_executor: ExecutorEnvironment) -> ExecutorEnvironment:
    return replace(pod_executor, cwd="/state/workspaces/central-acceptance")


@pytest.fixture
def vm_executor() -> ExecutorEnvironment:
    return ExecutorEnvironment(
        template=VM_TEMPLATE,
        cwd=VM_WORKING_DIRECTORY,
        storage_case="vm-raw",
        workspace_dir="/state/workspaces",
        storage_cwd="/state/workspaces/.home",
        vm=True,
        sampler_probe=(
            "printf 'VM_PID1 %s\\n' \"$(cat /proc/1/comm)\"; "
            "printf 'VM_EXECUTOR_UID %s\\n' \"$(id -u)\"; "
            "printf 'VM_EXECUTOR_CGROUP %s\\n' \"$(awk -F: '$1 == 0 {print $3}' /proc/self/cgroup)\"; "
        ),
        verify_sampler_output=_verify_vm_executor,
    )
