"""Tests for Kyverno policies using the kyverno CLI."""

from __future__ import annotations

from pathlib import Path

import pytest_bazel

from cluster.validation.kyverno import apply_policy
from util.bazel.runfiles import get_required_path

INJECT_MITMPROXY_POLICY = Path("cluster/k8s/kyverno/policies/inject-mitmproxy-proxy.yaml")


def _testdata(name: str) -> Path:
    return get_required_path(f"_main/cluster/validation/testdata/kyverno/{name}")


def _policy(rel: str) -> Path:
    return get_required_path(f"_main/{rel}")


class TestInjectMitmproxyProxy:
    """Tests for the inject-mitmproxy-proxy ClusterPolicy."""

    def test_pod_without_init_containers(self):
        """init-container rule is skipped when pod has no initContainers."""
        result = apply_policy(
            _policy("cluster/k8s/kyverno/policies/inject-mitmproxy-proxy.yaml"),
            _testdata("pod_no_init_containers.yaml"),
        )
        assert result.ok
        assert result.passed == 2, f"Expected volume + container rules to pass\n{result.stdout}"
        assert result.skipped == 1, f"Expected init-container rule to be skipped\n{result.stdout}"

    def test_pod_with_init_containers(self):
        """All three rules apply when pod has initContainers."""
        result = apply_policy(
            _policy("cluster/k8s/kyverno/policies/inject-mitmproxy-proxy.yaml"),
            _testdata("pod_with_init_containers.yaml"),
        )
        assert result.ok
        assert result.passed == 3, f"Expected all three rules to pass\n{result.stdout}"
        assert result.skipped == 0, f"Expected no rules skipped\n{result.stdout}"

    def test_pod_in_other_namespace_not_mutated(self):
        """Policy does not match pods outside target namespaces."""
        result = apply_policy(
            _policy("cluster/k8s/kyverno/policies/inject-mitmproxy-proxy.yaml"), _testdata("pod_other_namespace.yaml")
        )
        assert result.ok
        assert result.passed == 0, f"Expected no rules to match\n{result.stdout}"


if __name__ == "__main__":
    pytest_bazel.main()
