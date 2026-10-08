"""Operational prompt construction without the integration app or its database."""

import pytest_bazel

from agentplane.runner import protocol_pb2
from agentplane.sandbox_service.instructions import (
    combine_instructions,
    render_kubernetes_admin_instructions,
    render_platform_instructions,
)
from agentplane.sandbox_service.protocol_pb2 import (
    SandboxBinding,
    SandboxDestination,
    ServiceAccount,
    SessionDefaults,
    SessionDestination,
)
from agentplane.sandbox_service.session_lifecycle import launch_spec

# gazelle:include_dep @pypi//protobuf


def test_kubernetes_admin_guidance_is_rendered_once_for_every_sandbox() -> None:
    actions_url = "http://agentplane-actions.test:8080"
    section = render_kubernetes_admin_instructions(actions_service_url=actions_url)
    platform = render_platform_instructions(
        egress_api_url="http://agentplane-egress.test",
        actions_service_url=actions_url,
        notifications_service_url="http://agentplane-notifications.test:8080",
    )
    assert platform.count(section) == 1
    assert "kubernetes_admin" in section
    assert "pods_exec" in section
    assert "resources_get" in section
    assert "kubectl auth can-i" in section
    assert "auto_approve_if" in section
    assert "manual operator approval" in section
    assert actions_url in section


def test_task_instructions_augment_platform_guidance() -> None:
    assert combine_instructions("  Platform  ", "  Task  ") == "Platform\n\nTask"
    assert combine_instructions("", "Task") == "Task"
    assert combine_instructions("Platform", "") == "Platform"


def _launched_instructions(overrides: dict[str, object]) -> str:
    return launch_spec(
        SessionDestination(
            sandbox=SandboxDestination(
                owner=ServiceAccount(namespace="test-namespace", name="test-owner"),
                sandbox="test-sandbox",
                sandbox_uid="test-sandbox-uid",
            ),
            session_id="test-session",
        ),
        overrides,
        binding=SandboxBinding(
            session_defaults=SessionDefaults(
                harness=protocol_pb2.HARNESS_CODEX, model="test-model", cwd="/test", instructions="Test preset task."
            )
        ),
        platform_instructions="Test platform guidance.",
    ).instructions


def test_launch_orders_platform_guidance_then_destination_then_task() -> None:
    instructions = _launched_instructions({})

    assert instructions.startswith("Test platform guidance.")
    assert instructions.index("test-session") < instructions.index("Test preset task.")
    assert instructions.endswith("Test preset task.")


def test_clearing_the_task_keeps_platform_guidance() -> None:
    instructions = _launched_instructions({"instructions": ""})

    assert instructions.startswith("Test platform guidance.")
    assert "Test preset task." not in instructions


if __name__ == "__main__":
    pytest_bazel.main()
