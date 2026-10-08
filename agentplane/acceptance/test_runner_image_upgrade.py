"""Manual live proof: replace a Sandbox runner image without moving native state.

Requires two published, digest-pinned runner images and a kubeconfig authorized to
read/patch *the fixture Sandbox* and read its replacement Pod. Run only with an
explicit upgrade image; the test creates and deletes its own Sandbox.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Awaitable, Callable
from uuid import uuid4

import pytest_bazel
from tenacity import AsyncRetrying, stop_after_delay, wait_fixed

from agentplane.acceptance.agent import Agent
from agentplane.app.client import Client, has_ready_pod
from agentplane.app.sandbox_models import SandboxView
from agentplane.runner import protocol_pb2
from agentplane.runner.harness import Harness
from agentplane.sandbox_service.models import OperatingMode

Sandboxes = Callable[..., Awaitable[SandboxView]]
POD_TRANSITION_SECONDS = 300.0
UPGRADE_IMAGE_ENV = "AGENTPLANE_ACCEPTANCE_UPGRADE_IMAGE"


def _kubectl(namespace: str, *args: str) -> dict[str, object]:
    result = subprocess.run(
        ["kubectl", "-n", namespace, *args, "-o", "json"], capture_output=True, text=True, check=False
    )
    if result.returncode:
        raise AssertionError(f"kubectl {args[0]} {args[1]} failed: {result.stderr.strip()}")
    value: dict[str, object] = json.loads(result.stdout)
    return value


def _runner_image(resource: dict[str, object]) -> tuple[int, str]:
    spec = resource["spec"]
    assert isinstance(spec, dict)
    pod_spec = spec.get("podTemplate", spec)
    assert isinstance(pod_spec, dict)
    if "spec" in pod_spec:
        pod_spec = pod_spec["spec"]
    assert isinstance(pod_spec, dict)
    containers = pod_spec["containers"]
    assert isinstance(containers, list)
    for index, container in enumerate(containers):
        assert isinstance(container, dict)
        if container.get("name") == "runner":
            image = container["image"]
            assert isinstance(image, str)
            return index, image
    raise AssertionError("Sandbox Pod template has no runner container")


def _metadata(resource: dict[str, object]) -> dict[str, object]:
    metadata = resource["metadata"]
    assert isinstance(metadata, dict)
    return metadata


async def _wait_for_pod_removed(client: Client, name: str) -> None:
    async for attempt in AsyncRetrying(stop=stop_after_delay(POD_TRANSITION_SECONDS), wait=wait_fixed(2), reraise=True):
        with attempt:
            view = await client.sandbox(name)
            assert view.operating_mode is OperatingMode.SUSPENDED
            assert view.pod is None


async def test_runner_image_upgrade_keeps_both_native_sessions(client: Client, sandbox: Sandboxes) -> None:
    upgraded_image = os.environ.get(UPGRADE_IMAGE_ENV)
    if not upgraded_image or "@sha256:" not in upgraded_image:
        raise AssertionError(f"Set {UPGRADE_IMAGE_ENV} to a published, digest-pinned runner image")

    view = await sandbox("accept-image-upgrade")
    namespace = view.namespace
    before = _kubectl(namespace, "get", "sandbox", view.name)
    metadata = _metadata(before)
    assert metadata["uid"] == str(view.uid)
    index, original_image = _runner_image(before)
    assert upgraded_image != original_image, "test must replace the existing runner image"
    assert view.pod is not None
    original_pod_uid = view.pod.uid

    catalog = await client.models()
    markers = {protocol_pb2.HARNESS_CLAUDE: f"CLAUDE-{uuid4().hex}", protocol_pb2.HARNESS_CODEX: f"CODEX-{uuid4().hex}"}
    agents: dict[protocol_pb2.Harness, Agent] = {}
    for harness in markers:
        offered = catalog.harnesses[Harness(protocol_pb2.Harness.Name(harness))]
        assert offered
        agent = await Agent.open(client, sandbox=view.name, harness=harness, model=offered[0])
        seed = await agent.run(f"Remember this exact token: {markers[harness]}. Do not use tools. Reply only ACK.")
        assert seed.input_confirmed
        agents[harness] = agent

    await client.suspend_sandbox(view.name)
    await _wait_for_pod_removed(client, view.name)
    # Test UID + resourceVersion + old image so a replacement or concurrent edit cannot be patched.
    patch = [
        {"op": "test", "path": "/metadata/uid", "value": str(view.uid)},
        {"op": "test", "path": "/metadata/resourceVersion", "value": metadata["resourceVersion"]},
        {"op": "test", "path": f"/spec/podTemplate/spec/containers/{index}/image", "value": original_image},
        {"op": "replace", "path": f"/spec/podTemplate/spec/containers/{index}/image", "value": upgraded_image},
    ]
    # Suspension itself updates the resourceVersion; read it again after the old Pod has gone.
    suspended = _kubectl(namespace, "get", "sandbox", view.name)
    assert _metadata(suspended)["uid"] == str(view.uid)
    assert _runner_image(suspended) == (index, original_image)
    patch[1]["value"] = _metadata(suspended)["resourceVersion"]
    changed = _kubectl(namespace, "patch", "sandbox", view.name, "--type=json", "-p", json.dumps(patch))
    assert _metadata(changed)["uid"] == str(view.uid)
    assert _runner_image(changed) == (index, upgraded_image)

    await client.resume_sandbox(view.name)
    async for attempt in AsyncRetrying(stop=stop_after_delay(POD_TRANSITION_SECONDS), wait=wait_fixed(2), reraise=True):
        with attempt:
            resumed = await client.sandbox(view.name)
            assert resumed.uid == view.uid
            assert has_ready_pod(resumed), "replacement Pod not Ready"
            assert resumed.pod is not None
            assert resumed.pod.uid != original_pod_uid, "controller kept the old Pod"
            pod = _kubectl(namespace, "get", "pod", resumed.pod.name)
            assert _runner_image(pod)[1] == upgraded_image, "Pod did not use the patched image"

    for harness, agent in agents.items():
        await agent.resume()
        turn = await agent.run("Do not use tools. Which exact token did I ask you to remember? Reply only with it.")
        assert turn.resumed, f"{protocol_pb2.Harness.Name(harness)} did not resume native state"
        assert turn.input_confirmed
        assert markers[harness] in turn.answer, f"{protocol_pb2.Harness.Name(harness)} forgot its token"
        assert all(other not in turn.answer for other_harness, other in markers.items() if other_harness != harness)


if __name__ == "__main__":
    pytest_bazel.main()
