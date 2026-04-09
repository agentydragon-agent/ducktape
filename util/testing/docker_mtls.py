"""pytest fixture for Docker mTLS cert assembly.

Assembles a Docker cert directory from:
- Public certs (ca.pem, client-cert.pem) from Bazel runfiles
- Client private key from DOCKER_CLIENT_KEY env var

Sets DOCKER_CERT_PATH so docker.from_env() picks up mTLS automatically.
No-op when DOCKER_CLIENT_KEY is not set (falls back to non-TLS Docker).
"""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

import pytest
from rules_python.python.runfiles import runfiles

_RLOCATION_CA = "_main/cluster/k8s/docker-ci/certs/ca.pem"
_RLOCATION_CLIENT_CERT = "_main/cluster/k8s/docker-ci/certs/client-cert.pem"


@pytest.fixture(autouse=True)
def docker_mtls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Assemble Docker mTLS cert dir if DOCKER_CLIENT_KEY is set."""
    client_key = os.environ.get("DOCKER_CLIENT_KEY")
    if not client_key:
        return

    cert_dir = tmp_path / "docker-certs"
    cert_dir.mkdir()

    r = runfiles.Create()
    ca_path = r.Rlocation(_RLOCATION_CA)
    cert_path = r.Rlocation(_RLOCATION_CLIENT_CERT)
    if not ca_path or not cert_path:
        pytest.skip("Docker mTLS certs not in runfiles")

    # Docker expects exactly: ca.pem, cert.pem, key.pem
    shutil.copy(ca_path, cert_dir / "ca.pem")
    shutil.copy(cert_path, cert_dir / "cert.pem")

    key_file = cert_dir / "key.pem"
    key_file.write_text(client_key)
    key_file.chmod(stat.S_IRUSR)

    monkeypatch.setenv("DOCKER_CERT_PATH", str(cert_dir))
