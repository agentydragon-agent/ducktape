"""Unit tests for bazel_wrapper proxy credential refresh logic."""

from unittest.mock import patch

import pytest
import pytest_bazel

from devinfra.claude.bazel_wrapper import _refresh_proxy_creds
from devinfra.claude.errors import AuthProxyError
from devinfra.claude.session_paths import SessionPaths


def test_sends_creds_via_rpc(session_paths: SessionPaths, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://user:pass@proxy.example.com:8080")

    with patch("devinfra.claude.bazel_wrapper.update_proxy_creds") as mock_rpc:
        _refresh_proxy_creds(session_paths)
        mock_rpc.assert_called_once_with("http://user:pass@proxy.example.com:8080", session_paths)


def test_raises_when_no_proxy_env(session_paths: SessionPaths, monkeypatch: pytest.MonkeyPatch) -> None:
    """When HTTPS_PROXY is not set, raises AuthProxyError."""
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("https_proxy", raising=False)

    with pytest.raises(AuthProxyError, match="No HTTPS_PROXY"):
        _refresh_proxy_creds(session_paths)


def test_raises_when_rpc_fails(session_paths: SessionPaths, monkeypatch: pytest.MonkeyPatch) -> None:
    """When the RPC call fails with OSError, raises AuthProxyError with restart guidance."""
    monkeypatch.setenv("HTTPS_PROXY", "http://user:pass@proxy.example.com:8080")

    with (
        patch("devinfra.claude.bazel_wrapper.update_proxy_creds", side_effect=OSError("connection refused")),
        pytest.raises(AuthProxyError, match="Auth proxy RPC failed"),
    ):
        _refresh_proxy_creds(session_paths)


if __name__ == "__main__":
    pytest_bazel.main()
