"""Tests for secret_sources."""

import base64
from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import pytest_bazel
import yaml
from kubernetes.client import Configuration

from devinfra.claude.auth_proxy.vars import PROXY_ENV_VARS
from devinfra.claude.hook_config import K8sConfig, K8sSecretSource, SopsSecretSource
from devinfra.claude.hook_daemon.session_start.secret_sources import (
    read_k8s_secret,
    resolve_secret,
    setup_k8s_client,
    write_kubeconfig,
)

_K8S_CFG = K8sConfig(
    server="https://k8s.example.com",
    service_account="test-sa",
    service_account_namespace="default",
    namespace="secrets-ns",
)


def _make_mock_k8s_secret(data: dict[str, str]) -> MagicMock:
    """Create a mock k8s Secret with base64-encoded data."""
    secret = MagicMock()
    secret.data = {k: base64.b64encode(v.encode()).decode() for k, v in data.items()}
    return secret


@pytest.fixture
def mock_k8s_api() -> Generator[MagicMock]:
    """Mock the kubernetes CoreV1Api."""
    with (
        patch("devinfra.claude.hook_daemon.session_start.secret_sources.k8s_client"),
        patch("devinfra.claude.hook_daemon.session_start.secret_sources.CoreV1Api") as mock_api_cls,
    ):
        mock_api = MagicMock()
        mock_api_cls.return_value = mock_api
        yield mock_api


def test_read_k8s_secret(mock_k8s_api: MagicMock) -> None:
    """Read a single key from a k8s Secret."""
    mock_k8s_api.read_namespaced_secret.return_value = _make_mock_k8s_secret({"token": "my-token"})
    result = read_k8s_secret(mock_k8s_api, "ns", "secret-name", "token")
    assert result == "my-token"


def test_read_k8s_secret_missing_key(mock_k8s_api: MagicMock) -> None:
    """Returns None when the requested key is not in the secret."""
    mock_k8s_api.read_namespaced_secret.return_value = _make_mock_k8s_secret({"other": "val"})
    result = read_k8s_secret(mock_k8s_api, "ns", "secret-name", "token")
    assert result is None


def test_resolve_k8s_secret(mock_k8s_api: MagicMock) -> None:
    """resolve_secret dispatches K8sSecretSource to read_k8s_secret."""
    mock_k8s_api.read_namespaced_secret.return_value = _make_mock_k8s_secret({"key": "value"})
    source = K8sSecretSource(kind="k8s", secret_name="my-secret", key="key")
    result = resolve_secret(
        source, project_dir=Path("/unused"), age_identities=None, k8s_api=mock_k8s_api, k8s_namespace="ns"
    )
    assert result == "value"


def test_resolve_k8s_secret_no_client() -> None:
    """resolve_secret returns None when k8s client is unavailable."""
    source = K8sSecretSource(kind="k8s", secret_name="my-secret", key="key")
    result = resolve_secret(source, project_dir=Path("/unused"), age_identities=None, k8s_api=None, k8s_namespace=None)
    assert result is None


def test_resolve_sops_secret(tmp_path: Path) -> None:
    """resolve_secret dispatches SopsSecretSource to SOPS decryption."""
    source = SopsSecretSource(kind="sops", sops_file="secrets/test.yaml", key="my_key")
    with patch(
        "devinfra.claude.hook_daemon.session_start.secret_sources.decrypt_sops_yaml",
        return_value={"my_key": "decrypted_value"},
    ):
        result = resolve_secret(
            source, project_dir=tmp_path, age_identities=["fake-identity"], k8s_api=None, k8s_namespace=None
        )
    assert result == "decrypted_value"


def test_resolve_sops_secret_no_identities() -> None:
    """resolve_secret returns None when age identities are unavailable."""
    source = SopsSecretSource(kind="sops", sops_file="secrets/test.yaml", key="my_key")
    result = resolve_secret(source, project_dir=Path("/unused"), age_identities=None, k8s_api=None, k8s_namespace=None)
    assert result is None


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


def test_proxy_credentials_extracted(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proxy URL with embedded credentials sets Proxy-Authorization and sanitizes client proxy URL."""
    for var in PROXY_ENV_VARS:
        monkeypatch.delenv(var, raising=False)

    captured_configs: list[Configuration] = []

    class CapturingConfiguration(Configuration):
        def __init__(self) -> None:
            super().__init__()
            captured_configs.append(self)

    with (
        patch("devinfra.claude.hook_daemon.session_start.secret_sources.k8s_client"),
        patch("devinfra.claude.hook_daemon.session_start.secret_sources.CoreV1Api"),
        patch("devinfra.claude.hook_daemon.session_start.secret_sources.Configuration", CapturingConfiguration),
    ):
        setup_k8s_client(
            token="tok", k8s_cfg=_K8S_CFG, combined_ca_path=None, proxy="http://user:secret@proxy.example.com:8080"
        )

    assert len(captured_configs) == 1
    cfg = captured_configs[0]
    # Credentials must be stripped from the proxy URL used by the k8s client
    assert cfg.proxy == "http://proxy.example.com:8080"
    # Credentials must be sent via explicit Proxy-Authorization header
    expected_auth = "Basic " + base64.b64encode(b"user:secret").decode()
    assert cfg.proxy_headers == {"Proxy-Authorization": expected_auth}


if __name__ == "__main__":
    pytest_bazel.main()
