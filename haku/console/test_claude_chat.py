"""Focused contracts for the Agent Sandbox Claude chat runtime."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

import pytest_bazel

from haku.console.claude_chat import KubernetesSandboxClaims, _text_delta
from haku.console.config import ClaudeRuntimeConfig


class RecordingCustomObjectsApi:
    def __init__(self) -> None:
        self.created: tuple[tuple[Any, ...], dict[str, Any]] | None = None

    async def create_namespaced_custom_object(self, *args: Any, **kwargs: Any) -> None:
        self.created = (args, kwargs)


async def test_claim_injects_only_the_session_rendezvous_values() -> None:
    config = ClaudeRuntimeConfig(
        oauth_placeholder="sk-ant-oat01-proxy-haku-claude-placeholder", https_proxy="http://proxy.test:8180"
    )
    claims = KubernetesSandboxClaims(config)
    api = RecordingCustomObjectsApi()
    claims._custom_objects = cast(Any, api)
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
