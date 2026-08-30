"""Artifact tests for both SandboxClaim compositions."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import pytest_bazel

from haku.sandbox.claims import SandboxClaimSpec, build_sandbox_claim


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        (
            SandboxClaimSpec(
                namespace="haku-claude-sandbox",
                name="claude-10000000000040008000000000000001",
                warm_pool="haku-claude",
                labels={"app.kubernetes.io/managed-by": "haku-console", "haku.allegedly.works/harness": "claude"},
                annotations={},
                shutdown_policy="DeleteForeground",
                shutdown_time=datetime(2026, 8, 1, 5, 0, tzinfo=UTC),
                env={
                    "RUNNER_VAR": "environment",
                    "HAKU_RUNNER_SESSION_ID": "10000000-0000-4000-8000-000000000001",
                    "HAKU_SESSION_TOKEN": "session-secret",
                    "HAKU_RUNNER_TOKEN": "session-secret",
                },
            ),
            {
                "apiVersion": "extensions.agents.x-k8s.io/v1beta1",
                "kind": "SandboxClaim",
                "metadata": {
                    "name": "claude-10000000000040008000000000000001",
                    "labels": {
                        "app.kubernetes.io/managed-by": "haku-console",
                        "haku.allegedly.works/harness": "claude",
                    },
                },
                "spec": {
                    "warmPoolRef": {"name": "haku-claude"},
                    "lifecycle": {"shutdownPolicy": "DeleteForeground", "shutdownTime": "2026-08-01T05:00:00Z"},
                    "env": [
                        {"name": "RUNNER_VAR", "value": "environment"},
                        {"name": "HAKU_RUNNER_SESSION_ID", "value": "10000000-0000-4000-8000-000000000001"},
                        {"name": "HAKU_SESSION_TOKEN", "value": "session-secret"},
                        {"name": "HAKU_RUNNER_TOKEN", "value": "session-secret"},
                    ],
                },
            },
        ),
        (
            SandboxClaimSpec(
                namespace="agent-workspaces",
                name="task-one",
                warm_pool="test-pool",
                labels={"app.kubernetes.io/managed-by": "haku-sandbox-mcp"},
                annotations={
                    "haku.allegedly.works/sandbox-warm-pool": "test-pool",
                    "haku.allegedly.works/sandbox-container": "workspace",
                    "haku.allegedly.works/sandbox-default-cwd": "/test/workspace/test-state",
                    "haku.allegedly.works/sandbox-bootstrap-state": "pending",
                },
                shutdown_policy="Delete",
                shutdown_time=datetime(2026, 7, 22, 20, 0, tzinfo=UTC),
            ),
            {
                "apiVersion": "extensions.agents.x-k8s.io/v1beta1",
                "kind": "SandboxClaim",
                "metadata": {
                    "name": "task-one",
                    "labels": {"app.kubernetes.io/managed-by": "haku-sandbox-mcp"},
                    "annotations": {
                        "haku.allegedly.works/sandbox-warm-pool": "test-pool",
                        "haku.allegedly.works/sandbox-container": "workspace",
                        "haku.allegedly.works/sandbox-default-cwd": "/test/workspace/test-state",
                        "haku.allegedly.works/sandbox-bootstrap-state": "pending",
                    },
                },
                "spec": {
                    "warmPoolRef": {"name": "test-pool"},
                    "lifecycle": {"shutdownPolicy": "Delete", "shutdownTime": "2026-07-22T20:00:00Z"},
                },
            },
        ),
    ],
)
def test_build_claim_matches_current_path_artifact(spec: SandboxClaimSpec, expected: dict) -> None:
    assert build_sandbox_claim(spec) == expected


if __name__ == "__main__":
    pytest_bazel.main()
