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
    values: dict[str, object] = {
        "version": 2,
        "control": {"target": "test-gateway.test:7100", "bearer": "test-control-placeholder"},
        "ingress": {"target": "test-history.test:8081", "bearer": "test-ingress-placeholder"},
        "resources": _resources(),
        "llm_base_url": "http://llm-ingress.agentplane.svc.cluster.local:8080",
        "proxy_url": "http://10.0.2.2:3128",
        "platform_instructions": "Test platform guidance.",
    }
    return GuestConfig.model_validate(values | updates)


def test_guest_seed_serializes_origin_urls_without_trailing_slashes() -> None:
    config = _config(llm_base_url="HTTPS://LLM.Example:8443/", proxy_url="http://Proxy.Example:3128/")

    serialized = json.loads(config.model_dump_json())

    assert serialized == {
        "version": 2,
        "control": {"target": "test-gateway.test:7100", "bearer": "test-control-placeholder"},
        "ingress": {"target": "test-history.test:8081", "bearer": "test-ingress-placeholder"},
        "resources": _resources(),
        "llm_base_url": "https://llm.example:8443",
        "proxy_url": "http://proxy.example:3128",
        "platform_instructions": "Test platform guidance.",
        "console_autologin": False,
        "harness_env": None,
    }


def test_harness_env_reaches_the_guest_seed_only_when_set() -> None:
    assert "harness_env" not in json.loads(_config().model_dump_json(exclude_defaults=True))

    seeded = json.loads(_config(harness_env={"EXAMPLE_NAME": "value"}).model_dump_json(exclude_defaults=True))

    assert seeded["harness_env"] == {"EXAMPLE_NAME": "value"}


def test_guest_resource_budgets_are_typed_and_fit_guest_headroom() -> None:
    resources = GuestResources.model_validate(_resources())

    assert resources.guest_memory_bytes == 1_610_612_736
    assert resources.service_memory_max_bytes == resources.guest_memory_bytes - resources.os_reserve_bytes
    assert resources.aggregate.memory_max_bytes == 1_140_850_688
    assert resources.process.memory_max_bytes == 805_306_368


@pytest.mark.parametrize(
    "updates",
    [
        {"version": 1},
        {"control": {"target": "test-gateway.test:7100"}},
        {"ingress": {"target": "", "bearer": "test-ingress-placeholder"}},
        {"llm_base_url": "ftp://model.test"},
        {"llm_base_url": "model.test"},
        {"proxy_url": "http://proxy.test:65536"},
        {"proxy_url": "http://proxy.test:0"},
        {"llm_base_url": "https://user:password@model.test"},
        {"llm_base_url": "https://model.test/v1"},
        {"proxy_url": "http://proxy.test/path"},
        {"platform_instructions": ""},
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
