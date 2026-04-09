"""Tests for secret_sources."""

from pathlib import Path
from unittest.mock import patch

import pytest_bazel
import yaml

from devinfra.claude.hook_daemon.config import K8sConfig, SopsSecretSource
from devinfra.claude.hook_daemon.session_start.secret_sources import resolve_secret, write_kubeconfig

_K8S_CFG = K8sConfig(
    server="https://k8s.example.com",
    service_account="test-sa",
    service_account_namespace="default",
    namespace="secrets-ns",
)


def test_resolve_sops_secret(tmp_path: Path) -> None:
    """resolve_secret dispatches SopsSecretSource to SOPS decryption."""
    source = SopsSecretSource(kind="sops", sops_file="secrets/test.yaml", key="my_key")
    with patch(
        "devinfra.claude.hook_daemon.session_start.secret_sources.decrypt_sops_yaml",
        return_value={"my_key": "decrypted_value"},
    ):
        result = resolve_secret(source, project_dir=tmp_path)
    assert result == "decrypted_value"


def test_kubeconfig_proxy_url(tmp_path: Path) -> None:
    """When proxy is set, kubeconfig should include proxy-url in the cluster config."""
    path = write_kubeconfig(
        token="tok", k8s_cfg=_K8S_CFG, session_dir=tmp_path, combined_ca_path=None, proxy_url="http://localhost:18081"
    )
    kubeconfig = yaml.safe_load(path.read_text())
    assert kubeconfig["clusters"][0]["cluster"]["proxy-url"] == "http://localhost:18081"


def test_kubeconfig_no_proxy_url_when_unset(tmp_path: Path) -> None:
    """When proxy is not set, kubeconfig should not include proxy-url."""
    path = write_kubeconfig(token="tok", k8s_cfg=_K8S_CFG, session_dir=tmp_path, combined_ca_path=None, proxy_url=None)
    kubeconfig = yaml.safe_load(path.read_text())
    assert "proxy-url" not in kubeconfig["clusters"][0]["cluster"]


def test_kubeconfig_proxy_url_explicit(tmp_path: Path) -> None:
    """Explicit proxy arg is written to the kubeconfig proxy-url."""
    path = write_kubeconfig(
        token="tok",
        k8s_cfg=_K8S_CFG,
        session_dir=tmp_path,
        combined_ca_path=None,
        proxy_url="http://egress-proxy:15004",
    )
    kubeconfig = yaml.safe_load(path.read_text())
    assert kubeconfig["clusters"][0]["cluster"]["proxy-url"] == "http://egress-proxy:15004"


if __name__ == "__main__":
    pytest_bazel.main()
