"""Tests for the standalone kubeconfig writer."""

import base64
import subprocess
from pathlib import Path

import pytest
import pytest_bazel
import yaml

from devinfra.claude.scripts import write_kubeconfig

_FAKE_CERT = "-----BEGIN CERTIFICATE-----\nFAKE-CERT\n-----END CERTIFICATE-----\n"
_FAKE_KEY = "-----BEGIN RSA PRIVATE KEY-----\nFAKE-KEY\n-----END RSA PRIVATE KEY-----\n"

_KUBECONFIG = {
    "apiVersion": "v1",
    "kind": "Config",
    "clusters": [{"cluster": {"server": "https://k8s.example.com"}, "name": "cluster"}],
    "contexts": [{"context": {"cluster": "cluster", "namespace": "ns", "user": "u"}, "name": "u"}],
    "current-context": "u",
    "users": [
        {
            "name": "u",
            "user": {
                "client-certificate-data": base64.b64encode(_FAKE_CERT.encode()).decode(),
                "client-key-data": base64.b64encode(_FAKE_KEY.encode()).decode(),
            },
        }
    ],
}


def test_build_kubeconfig_proxy_url() -> None:
    kc = write_kubeconfig.build_kubeconfig(
        client_cert=_FAKE_CERT,
        client_key=_FAKE_KEY,
        server="https://k8s.example.com",
        user="test-user",
        namespace="secrets-ns",
        ca_path=None,
        proxy_url="http://localhost:18081",
    )
    assert kc["clusters"][0]["cluster"]["proxy-url"] == "http://localhost:18081"


def test_build_kubeconfig_no_proxy_url() -> None:
    kc = write_kubeconfig.build_kubeconfig(
        client_cert=_FAKE_CERT,
        client_key=_FAKE_KEY,
        server="https://k8s.example.com",
        user="test-user",
        namespace="secrets-ns",
        ca_path=None,
        proxy_url=None,
    )
    assert "proxy-url" not in kc["clusters"][0]["cluster"]


def test_build_kubeconfig_ca_data(tmp_path: Path) -> None:
    ca_file = tmp_path / "ca.pem"
    ca_file.write_text("-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----\n")
    kc = write_kubeconfig.build_kubeconfig(
        client_cert=_FAKE_CERT,
        client_key=_FAKE_KEY,
        server="https://k8s.example.com",
        user="test-user",
        namespace="secrets-ns",
        ca_path=ca_file,
        proxy_url=None,
    )
    assert "certificate-authority-data" in kc["clusters"][0]["cluster"]


def test_build_kubeconfig_client_cert_data() -> None:
    kc = write_kubeconfig.build_kubeconfig(
        client_cert=_FAKE_CERT,
        client_key=_FAKE_KEY,
        server="https://k8s.example.com",
        user="test-user",
        namespace="ns",
        ca_path=None,
        proxy_url=None,
    )
    user_data = kc["users"][0]["user"]
    assert base64.b64decode(user_data["client-certificate-data"]).decode() == _FAKE_CERT
    assert base64.b64decode(user_data["client-key-data"]).decode() == _FAKE_KEY


def test_write_kubeconfig_file_fresh(tmp_path: Path) -> None:
    output = tmp_path / "kubeconfig"
    write_kubeconfig.write_kubeconfig_file(_KUBECONFIG, output)
    assert yaml.safe_load(output.read_text()) == _KUBECONFIG
    assert output.stat().st_mode & 0o777 == 0o600


def test_write_kubeconfig_file_noop_when_identical(tmp_path: Path) -> None:
    output = tmp_path / "kubeconfig"
    write_kubeconfig.write_kubeconfig_file(_KUBECONFIG, output)
    mtime = output.stat().st_mtime_ns
    write_kubeconfig.write_kubeconfig_file(_KUBECONFIG, output)
    assert output.stat().st_mtime_ns == mtime


def test_write_kubeconfig_file_refuses_to_clobber(tmp_path: Path) -> None:
    output = tmp_path / "kubeconfig"
    other = {**_KUBECONFIG, "current-context": "different"}
    output.write_text(yaml.safe_dump(other))
    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        write_kubeconfig.write_kubeconfig_file(_KUBECONFIG, output)
    assert yaml.safe_load(output.read_text()) == other


def test_write_kubeconfig_file_refuses_on_invalid_yaml(tmp_path: Path) -> None:
    output = tmp_path / "kubeconfig"
    output.write_text("not: valid: yaml: [")
    with pytest.raises(RuntimeError, match="not valid YAML"):
        write_kubeconfig.write_kubeconfig_file(_KUBECONFIG, output)


def _make_fake_sops(cert: str = _FAKE_CERT, key: str = _FAKE_KEY):
    """Return a sops stub that returns cert or key depending on --extract arg."""

    def _fake_sops(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        assert cmd[0] == "sops"
        extract_arg = cmd[cmd.index("--extract") + 1]
        if "client_cert" in extract_arg:
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=cert.encode(), stderr=b"")
        if "client_key" in extract_arg:
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=key.encode(), stderr=b"")
        raise AssertionError(f"unexpected --extract arg: {extract_arg}")

    return _fake_sops


def test_main_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_dir = tmp_path / "repo"
    (project_dir / "secrets").mkdir(parents=True)
    (project_dir / "secrets" / "claude-web-k8s-cert.yaml").write_text("stub")

    fake_system_ca = tmp_path / "system-ca.pem"
    ca_pem = "-----BEGIN CERTIFICATE-----\nFAKE-CA-DATA\n-----END CERTIFICATE-----\n"
    fake_system_ca.write_text(ca_pem)
    monkeypatch.setattr(write_kubeconfig, "_SYSTEM_CA_BUNDLE", fake_system_ca)

    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project_dir))
    monkeypatch.setenv("HTTPS_PROXY", "http://egress.example.test:3128")
    monkeypatch.setattr(write_kubeconfig.subprocess, "run", _make_fake_sops())

    output_path = tmp_path / "out" / "kubeconfig"
    write_kubeconfig.main([str(output_path), "--server", "https://api.example.test:443"])

    kubeconfig = yaml.safe_load(output_path.read_text())
    cluster = kubeconfig["clusters"][0]["cluster"]
    assert cluster["server"] == "https://api.example.test:443"
    assert cluster["proxy-url"] == "http://egress.example.test:3128"
    assert cluster["certificate-authority-data"] == base64.b64encode(ca_pem.encode()).decode()
    user_data = kubeconfig["users"][0]["user"]
    assert base64.b64decode(user_data["client-certificate-data"]).decode() == _FAKE_CERT.strip()
    assert base64.b64decode(user_data["client-key-data"]).decode() == _FAKE_KEY.strip()
    assert kubeconfig["current-context"] == "claude-code-web"
    assert output_path.stat().st_mode & 0o777 == 0o600


def test_main_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Uses baked-in defaults when no --server/--user/--namespace given."""
    project_dir = tmp_path / "repo"
    (project_dir / "secrets").mkdir(parents=True)
    (project_dir / "secrets" / "claude-web-k8s-cert.yaml").write_text("stub")

    monkeypatch.setattr(write_kubeconfig, "_SYSTEM_CA_BUNDLE", tmp_path / "nonexistent")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project_dir))
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("https_proxy", raising=False)
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("http_proxy", raising=False)
    monkeypatch.setattr(write_kubeconfig.subprocess, "run", _make_fake_sops())

    output_path = tmp_path / "kubeconfig"
    write_kubeconfig.main([str(output_path)])

    kubeconfig = yaml.safe_load(output_path.read_text())
    cluster = kubeconfig["clusters"][0]["cluster"]
    assert cluster["server"] == "https://api.allegedly.works"
    assert kubeconfig["current-context"] == "claude-code-web"
    assert "proxy-url" not in cluster


if __name__ == "__main__":
    pytest_bazel.main()
