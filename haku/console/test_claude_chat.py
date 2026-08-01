"""Focused contracts for the Agent Sandbox Claude chat runtime."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

import pytest_bazel
from kubernetes_asyncio import client as k8s_client

from haku.console.claude_chat import KubernetesSandboxClaims, _text_delta
from haku.console.config import ClaudeRuntimeConfig


class RecordingCustomObjectsApi:
    def __init__(self) -> None:
        self.created: tuple[tuple[Any, ...], dict[str, Any]] | None = None
        self.objects: dict[tuple[str, str], dict[str, Any]] = {}

    async def create_namespaced_custom_object(self, *args: Any, **kwargs: Any) -> None:
        self.created = (args, kwargs)

    async def get_namespaced_custom_object(
        self, group: str, version: str, namespace: str, plural: str, name: str
    ) -> dict[str, Any]:
        del group, version, namespace
        return self.objects[(plural, name)]


class RecordingCoreV1Api:
    def __init__(self) -> None:
        self.pods: dict[str, k8s_client.V1Pod] = {}

    async def read_namespaced_pod(self, name: str, namespace: str) -> k8s_client.V1Pod:
        del namespace
        return self.pods[name]


def _claims(
    config: ClaudeRuntimeConfig,
) -> tuple[KubernetesSandboxClaims, RecordingCustomObjectsApi, RecordingCoreV1Api]:
    claims = KubernetesSandboxClaims(config)
    custom = RecordingCustomObjectsApi()
    core = RecordingCoreV1Api()
    claims._custom_objects = cast(Any, custom)
    claims._core_v1 = cast(Any, core)
    return claims, custom, core


async def test_claim_injects_only_the_session_rendezvous_values() -> None:
    config = ClaudeRuntimeConfig(
        oauth_placeholder="sk-ant-oat01-proxy-haku-claude-placeholder", https_proxy="http://proxy.test:8180"
    )
    claims, api, _ = _claims(config)
    session_id = UUID("10000000-0000-4000-8000-000000000001")

    await claims.create(
        session_id=session_id, bridge_token="one-use-secret", expires_at=datetime(2026, 8, 1, 5, 0, tzinfo=UTC)
    )

    assert api.created is not None
    args, _ = api.created
    assert args[:4] == ("extensions.agents.x-k8s.io", "v1beta1", "haku-sandbox", "sandboxclaims")
    body = args[4]
    assert body["metadata"]["name"] == "claude-10000000000040008000000000000001"
    assert body["spec"]["warmPoolRef"] == {"name": "haku-claude"}
    assert body["spec"]["env"] == [
        {"name": "HAKU_CLAUDE_SESSION_ID", "value": str(session_id)},
        {"name": "HAKU_AGENT_SDK_RUNNER_TOKEN", "value": "one-use-secret"},
    ]
    assert body["spec"]["lifecycle"] == {"shutdownPolicy": "DeleteForeground", "shutdownTime": "2026-08-01T05:00:00Z"}


async def test_inspect_reports_each_underlying_provisioning_layer() -> None:
    config = ClaudeRuntimeConfig(oauth_placeholder="not-a-secret", https_proxy="http://proxy.test:8180")
    claims, custom, core = _claims(config)
    session_id = UUID("10000000-0000-4000-8000-000000000001")
    claim_name = "claude-10000000000040008000000000000001"
    custom.objects[("sandboxclaims", claim_name)] = {
        "status": {
            "sandbox": {"name": "sandbox-abc"},
            "conditions": [{"type": "Ready", "status": "False", "reason": "PodNotReady", "message": "Waiting for Pod"}],
        }
    }
    custom.objects[("sandboxes", "sandbox-abc")] = {
        "metadata": {"annotations": {"agents.x-k8s.io/pod-name": "sandbox-pod-abc"}},
        "status": {"conditions": [{"type": "Ready", "status": "False"}]},
    }
    core.pods["sandbox-pod-abc"] = k8s_client.V1Pod(
        status=k8s_client.V1PodStatus(
            phase="Pending",
            conditions=[k8s_client.V1PodCondition(type="Ready", status="False")],
            container_statuses=[
                k8s_client.V1ContainerStatus(
                    name="runner",
                    image="runner:test",
                    image_id="",
                    ready=False,
                    restart_count=0,
                    state=k8s_client.V1ContainerState(
                        waiting=k8s_client.V1ContainerStateWaiting(reason="ContainerCreating")
                    ),
                )
            ],
        )
    )

    info = await claims.inspect(session_id=session_id)

    assert info.step == "waiting_for_pod_ready"
    assert info.claim_name == claim_name
    assert info.claim_ready is False
    assert info.claim_reason == "PodNotReady"
    assert info.claim_message == "Waiting for Pod"
    assert info.sandbox_name == "sandbox-abc"
    assert info.sandbox_ready is False
    assert info.pod_name == "sandbox-pod-abc"
    assert info.pod_phase == "Pending"
    assert info.pod_ready is False
    assert info.runner_ready is False
    assert info.runner_state == "waiting: ContainerCreating"


async def test_inspect_distinguishes_ready_pod_from_runner_bridge_wait() -> None:
    config = ClaudeRuntimeConfig(oauth_placeholder="not-a-secret", https_proxy="http://proxy.test:8180")
    claims, custom, core = _claims(config)
    session_id = UUID("10000000-0000-4000-8000-000000000001")
    claim_name = "claude-10000000000040008000000000000001"
    custom.objects[("sandboxclaims", claim_name)] = {
        "status": {"sandbox": {"name": "sandbox-abc"}, "conditions": [{"type": "Ready", "status": "True"}]}
    }
    custom.objects[("sandboxes", "sandbox-abc")] = {
        "metadata": {},
        "status": {"conditions": [{"type": "Ready", "status": "True"}]},
    }
    core.pods["sandbox-abc"] = k8s_client.V1Pod(
        status=k8s_client.V1PodStatus(
            phase="Running",
            conditions=[k8s_client.V1PodCondition(type="Ready", status="True")],
            container_statuses=[
                k8s_client.V1ContainerStatus(
                    name="runner",
                    image="runner:test",
                    image_id="runner:test",
                    ready=True,
                    restart_count=0,
                    state=k8s_client.V1ContainerState(running=k8s_client.V1ContainerStateRunning()),
                )
            ],
        )
    )

    info = await claims.inspect(session_id=session_id)

    assert info.step == "waiting_for_runner"
    assert info.claim_ready is True
    assert info.sandbox_ready is True
    assert info.pod_ready is True
    assert info.runner_ready is True
    assert info.runner_state == "running"


def test_claude_environment_contains_placeholder_proxy_and_ca_only() -> None:
    config = ClaudeRuntimeConfig(
        oauth_placeholder="not-a-secret", https_proxy="http://proxy.test:8180", ca_bundle="/ca/bundle.pem"
    )

    assert config.claude_environment() == {
        "CLAUDE_CODE_OAUTH_TOKEN": "not-a-secret",
        "HTTP_PROXY": "http://proxy.test:8180",
        "HTTPS_PROXY": "http://proxy.test:8180",
        "NO_PROXY": "127.0.0.1,localhost,.svc,.svc.cluster.local,kubernetes.default.svc,10.0.0.0/8",
        "NODE_USE_ENV_PROXY": "1",
        "NODE_EXTRA_CA_CERTS": "/ca/bundle.pem",
        "SSL_CERT_FILE": "/ca/bundle.pem",
        "CURL_CA_BUNDLE": "/ca/bundle.pem",
        "REQUESTS_CA_BUNDLE": "/ca/bundle.pem",
    }


def test_text_delta_ignores_non_text_stream_events() -> None:
    assert _text_delta({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hi"}}) == "hi"
    assert _text_delta({"type": "content_block_delta", "delta": {"type": "input_json_delta"}}) == ""
    assert _text_delta({"type": "message_start"}) == ""


if __name__ == "__main__":
    pytest_bazel.main()
