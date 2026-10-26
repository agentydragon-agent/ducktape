"""The guest config the VM SandboxTemplate carries."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, cast

import pytest
import pytest_bazel
from cdk8s import (
    Chart,
    Testing as Cdk8sTesting,  # not collected by pytest
)
from more_itertools import one

from agentplane.runner.configuration import Configuration
from agentplane.sandboxes.guest_config import GuestConfig
from cluster.cdk8s.agentplane import runner_vm, staging

HARNESS_ENV = {"EXAMPLE_SERVICE_URL": "http://service.test"}


def _runner_vm_manifests(*, console_autologin: bool) -> dict[str, dict[str, Any]]:
    chart = Chart(Cdk8sTesting.app(), "test")
    runner_vm.RunnerVmTemplate(
        chart,
        "runner-vm-template",
        replace(staging.ENV, vm_console_autologin=console_autologin),
        labels={},
        state_volume={"claim": {"storageClassName": "test-storage"}},
        workspace_volume={
            "name": "workspace",
            "claim": {"storageClassName": "test-storage", "volumeMode": "Filesystem"},
            "layout": {"type": "RawDiskImage", "filesystem": "ext4"},
        },
        platform_instructions="Test platform guidance.",
        harness_env=HARNESS_ENV,
    )
    docs = cast(list[dict[str, Any]], Cdk8sTesting.synth(chart))
    config_map = one(
        doc for doc in docs if doc["kind"] == "ConfigMap" and doc["metadata"]["name"] == "runner-vm-config"
    )
    sandbox_template = one(doc for doc in docs if doc["kind"] == "SandboxTemplate")
    return {
        "config": cast(dict[str, Any], json.loads(config_map["data"]["vm.json"])),
        "runner": cast(dict[str, Any], json.loads(config_map["data"]["runner.json"])),
        "sandbox_template": sandbox_template,
    }


def _guest_config(*, console_autologin: bool) -> dict[str, Any]:
    return _runner_vm_manifests(console_autologin=console_autologin)["config"]


@pytest.mark.parametrize(("console_autologin", "rendered"), [(True, True), (False, False)])
def test_console_autologin_reaches_the_guest_config_only_when_enabled(console_autologin: bool, rendered: bool) -> None:
    assert _guest_config(console_autologin=console_autologin).get("console_autologin") == rendered


def test_harness_env_reaches_the_guest_config() -> None:
    rendered = _runner_vm_manifests(console_autologin=False)
    runner = Configuration.model_validate(rendered["runner"])
    boot = GuestConfig.model_validate(rendered["config"])
    assert all(runner.harness_environment.values[name] == value for name, value in HARNESS_ENV.items())
    assert runner.isolation is not None
    assert runner.isolation.aggregate == boot.resources.aggregate
    assert runner.isolation.process == boot.resources.process


def test_vm_size_and_guest_seed_share_the_configured_resources() -> None:
    rendered = _runner_vm_manifests(console_autologin=False)
    config = rendered["config"]
    vm = rendered["sandbox_template"]["spec"]["vm"]
    domain = vm["template"]["spec"]["domain"]

    assert domain["cpu"]["cores"] == config["resources"]["guest_vcpu_count"]
    memory = domain["resources"]["requests"]["memory"]
    assert int(memory.removesuffix("Mi")) * 1024 * 1024 == config["resources"]["guest_memory_bytes"]


def test_vm_workspace_is_a_controller_attached_raw_disk_image() -> None:
    template = _runner_vm_manifests(console_autologin=False)["sandbox_template"]["spec"]
    assert template["workspaceVolume"] == {
        "name": "workspace",
        "claim": {"storageClassName": "test-storage", "volumeMode": "Filesystem"},
        "layout": {"type": "RawDiskImage", "filesystem": "ext4"},
    }
    vm = template["vm"]
    disks = vm["template"]["spec"]["domain"]["devices"]["disks"]
    assert any(
        disk["name"] == "workspace" and disk["disk"]["bus"] == "virtio" and disk["serial"] == "workspace"
        for disk in disks
    )
    volumes = vm["template"]["spec"]["volumes"]
    assert "workspace" not in {volume["name"] for volume in volumes}
    assert "dataVolumeTemplates" not in vm


if __name__ == "__main__":
    pytest_bazel.main()
