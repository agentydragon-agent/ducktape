"""Validation and JSON contract for the public KubeVirt guest seed."""

import json

import pytest
import pytest_bazel
from pydantic import ValidationError

from agentplane.sandboxes.guest_config import GuestConfig, GuestResources


def _limits(*, memory: int, pids: int) -> dict[str, object]:
    return {
        "cpu_quota_micros": 100_000,
        "memory_max_bytes": memory,
        "pids_max": pids,
        "read_bps": 52_428_800,
        "write_bps": 20_971_520,
        "read_iops": 1000,
        "write_iops": 500,
    }


def _resources() -> dict[str, object]:
    return {
        "guest_memory_bytes": 1_610_612_736,
        "guest_vcpu_count": 1,
        "os_reserve_bytes": 268_435_456,
        "service_memory_high_bytes": 1_207_959_552,
        "service_memory_max_bytes": 1_342_177_280,
        "service_cpu_quota_micros": 100_000,
        "service_pids_max": 1024,
        "aggregate": _limits(memory=1_140_850_688, pids=768),
        "process": _limits(memory=805_306_368, pids=512),
    }


def _config(**updates: object) -> GuestConfig:
    return GuestConfig.model_validate({"version": 3, "resources": _resources(), **updates})


def test_boot_configuration_contains_only_vm_policy() -> None:
    assert json.loads(_config().model_dump_json()) == {
        "version": 3,
        "resources": {**_resources(), "executor": None},
        "console_autologin": False,
    }


def test_guest_resource_budgets_are_typed_and_fit_guest_headroom() -> None:
    resources = GuestResources.model_validate(_resources())

    assert resources.guest_memory_bytes == 1_610_612_736
    assert resources.service_memory_max_bytes == resources.guest_memory_bytes - resources.os_reserve_bytes
    assert resources.aggregate.memory_max_bytes == 1_140_850_688
    assert resources.process.memory_max_bytes == 805_306_368


@pytest.mark.parametrize(
    ("memory", "cpu", "pids", "valid"),
    [
        (67_108_864, 100_000, 128, True),
        (67_108_865, 100_000, 128, False),
        (67_108_864, 100_001, 128, False),
        (67_108_864, 100_000, 256, False),
    ],
)
def test_executor_budget_shares_outer_service_headroom(memory: int, cpu: int, pids: int, valid: bool) -> None:
    values = {**_resources(), "executor": {**_limits(memory=memory, pids=pids), "cpu_quota_micros": cpu}}
    if valid:
        resources = GuestResources.model_validate(values)
        assert resources.executor is not None
        assert (
            resources.aggregate.memory_max_bytes + resources.executor.memory_max_bytes
            <= resources.service_memory_high_bytes
        )
    else:
        with pytest.raises(ValidationError):
            GuestResources.model_validate(values)


@pytest.mark.parametrize(
    "updates",
    [
        {"version": 2},
        {"control": {"target": "test:7100", "bearer": "placeholder"}},
        {"platform_instructions": "moved to runner.json"},
        {"resources": {**_resources(), "service_memory_max_bytes": 1_610_612_736}},
        {"resources": {**_resources(), "aggregate": _limits(memory=805_306_367, pids=768)}},
        {"unexpected": "value"},
    ],
)
def test_invalid_guest_seed_is_rejected(updates: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _config(**updates)


if __name__ == "__main__":
    pytest_bazel.main()
