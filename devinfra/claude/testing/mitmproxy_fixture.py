"""Shared mitmproxy testcontainer fixture for proxy testing.

Starts a mitmproxy container (mitmdump) with TLS MITM and Basic auth.
Used by all tests that need an egress proxy simulation.
"""

import logging
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path

import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import wait_for_logs

from devinfra.claude.testing.proxy_ca import generate_mock_ca
from util.oci import load_image
from util.testing.undeclared_outputs import undeclared_outputs_dir

logger = logging.getLogger(__name__)

_MITMPROXY_IMAGE = "mitmproxy:11"
_MITMPROXY_TARBALL = "_main/devinfra/claude/testing/mitmproxy_load/tarball.tar"

_PROXY_LISTEN_PORT = 8080
_PROXY_USERNAME = "proxy_user"
_PROXY_PASSWORD = "test_jwt_token"


@dataclass(frozen=True)
class MitmproxyFixture:
    """Running mitmproxy container with proxy URL and CA cert."""

    url: str
    port: int
    ca_cert_pem: bytes
    container: DockerContainer


@pytest.fixture
def mitmproxy_proxy(tmp_path: Path) -> Generator[MitmproxyFixture]:
    """Start a mitmproxy container for proxy testing.

    Loads the mitmproxy:11 OCI image, generates a CA cert host-side,
    and starts mitmdump with Basic auth. The proxy port is published
    on a random host port.
    """
    load_image(_MITMPROXY_TARBALL)

    cert_pem, key_pem = generate_mock_ca()
    certs_dir = tmp_path / "mitmproxy_certs"
    certs_dir.mkdir()
    (certs_dir / "mitmproxy-ca.pem").write_bytes(key_pem + cert_pem)
    (certs_dir / "mitmproxy-ca-cert.pem").write_bytes(cert_pem)

    cmd = " ".join(
        [
            "mitmdump",
            "--listen-host",
            "0.0.0.0",
            "--listen-port",
            str(_PROXY_LISTEN_PORT),
            "--set",
            "confdir=/certs",
            "--set",
            f"proxyauth={_PROXY_USERNAME}:{_PROXY_PASSWORD}",
            "--ssl-insecure",
        ]
    )

    container = (
        DockerContainer(_MITMPROXY_IMAGE)
        .with_command(cmd)
        .with_exposed_ports(_PROXY_LISTEN_PORT)
        .with_volume_mapping(str(certs_dir), "/certs", "ro")
    )
    container.start()
    wait_for_logs(container, "Proxy server listening")
    logger.info("mitmproxy container ready")

    try:
        host_port = int(container.get_exposed_port(_PROXY_LISTEN_PORT))
        yield MitmproxyFixture(
            url=f"http://{_PROXY_USERNAME}:{_PROXY_PASSWORD}@127.0.0.1:{host_port}",
            port=host_port,
            ca_cert_pem=cert_pem,
            container=container,
        )
    finally:
        log_file = undeclared_outputs_dir() / "mitmproxy.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        stdout, stderr = container.get_logs()
        log_file.write_bytes(stdout + stderr)

        container.stop()
