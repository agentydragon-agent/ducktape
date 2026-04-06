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

    def test_pod_with_existing_volumes_not_merged(self):
        """Injected volume is appended, not merged into existing volumes.

        Regression test: patchStrategicMerge caused Kyverno autogen to merge
        the mitmproxy-ca-cert configMap into existing volume entries, producing
        invalid volumes with two types. JSON patches avoid this by appending.
        """
        policy = _policy("cluster/k8s/kyverno/policies/inject-mitmproxy-proxy.yaml")
        result = apply_policy(policy, _testdata("pod_with_existing_volumes.yaml"))
        assert result.ok
        assert len(result.mutated_resources) == 1, f"Expected 1 mutated resource\n{result.stdout}"
        pod = result.mutated_resources[0]
        spec = pod["spec"]

        # Volumes: original 'config' + injected 'mitmproxy-ca-cert', each with exactly one type
        volumes = spec["volumes"]
        vol_names = [v["name"] for v in volumes]
        assert "config" in vol_names, f"Original volume missing: {volumes}"
        assert "mitmproxy-ca-cert" in vol_names, f"Injected volume missing: {volumes}"
        for vol in volumes:
            volume_types = [k for k in vol if k != "name"]
            assert len(volume_types) == 1, f"Volume {vol['name']!r} has multiple types: {volume_types}"

        # Container: original env var preserved, proxy env vars injected
        container = spec["containers"][0]
        env_names = [e["name"] for e in container["env"]]
        assert "MY_VAR" in env_names, f"Original env var missing: {env_names}"
        for expected in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "SSL_CERT_FILE"):
            assert expected in env_names, f"{expected} not injected: {env_names}"

        # Container: original volumeMount preserved, mitmproxy mount injected
        mount_names = [m["name"] for m in container["volumeMounts"]]
        assert "config" in mount_names, f"Original mount missing: {mount_names}"
        assert "mitmproxy-ca-cert" in mount_names, f"Injected mount missing: {mount_names}"


if __name__ == "__main__":
    pytest_bazel.main()
