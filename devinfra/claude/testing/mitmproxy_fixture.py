"""Shared mitmproxy testcontainer fixture for proxy testing.

Starts a mitmproxy container (mitmdump) with TLS MITM, Basic auth, and
optional upstream proxy chaining. Used by all tests that need an egress
proxy simulation.
"""

import asyncio
import logging
import shutil
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiodocker
import pytest
import tenacity
from yarl import URL

from devinfra.claude.testing.proxy_ca import EgressProxyConfig, generate_mock_ca
from util.oci import load_image
from util.testing.undeclared_outputs import undeclared_outputs_dir

logger = logging.getLogger(__name__)

_MITMPROXY_IMAGE = "mitmproxy:11"
_MITMPROXY_TARBALL = "_main/devinfra/claude/testing/mitmproxy_load/tarball.tar"

_PROXY_LISTEN_PORT = 8080
_PROXY_USERNAME = "proxy_user"
_PROXY_PASSWORD = "test_jwt_token"
_PROXY_READY_TIMEOUT = 60


@dataclass(frozen=True)
class MitmproxyFixture:
    """Running mitmproxy container with proxy URL and CA cert."""

    url: str
    port: int
    ca_cert_pem: bytes
    log_file: Path


@tenacity.retry(
    stop=tenacity.stop_after_delay(_PROXY_READY_TIMEOUT),
    wait=tenacity.wait_fixed(0.3),
    retry=tenacity.retry_if_exception_type(OSError),
    reraise=True,
)
async def _wait_for_proxy_ready(host: str, port: int) -> None:
    """TCP connect to the proxy port until it accepts connections."""
    _, writer = await asyncio.open_connection(host, port)
    writer.close()
    await writer.wait_closed()


def _build_mitmproxy_cmd(upstream: EgressProxyConfig | None) -> list[str]:
    """Build mitmdump command line."""
    cmd = [
        "mitmdump",
        "--listen-host",
        "0.0.0.0",
        "--listen-port",
        str(_PROXY_LISTEN_PORT),
        "--set",
        "confdir=/certs",
        "--set",
        f"proxyauth={_PROXY_USERNAME}:{_PROXY_PASSWORD}",
    ]

    if upstream:
        url = URL.build(scheme="http", host=upstream.host, port=upstream.port)
        cmd += ["--mode", f"upstream:{url}"]
        if upstream.username and upstream.password:
            cmd += ["--upstream-auth", f"{upstream.username}:{upstream.password}"]
        if upstream.ca_bundle:
            cmd += ["--set", "ssl_verify_upstream_trusted_ca=/shared/upstream_ca.pem"]
        else:
            cmd += ["--ssl-insecure"]
    else:
        cmd += ["--ssl-insecure"]

    return cmd


@pytest.fixture
async def mitmproxy_proxy(tmp_path: Path) -> AsyncGenerator[MitmproxyFixture]:
    """Start a mitmproxy container for proxy testing.

    Loads the mitmproxy:11 OCI image, generates a CA cert host-side,
    and starts mitmdump with Basic auth and optional upstream chaining.
    The proxy port is published on a random host port.
    """
    load_image(_MITMPROXY_TARBALL)

    cert_pem, key_pem = generate_mock_ca()
    certs_dir = tmp_path / "mitmproxy_certs"
    certs_dir.mkdir()
    (certs_dir / "mitmproxy-ca.pem").write_bytes(key_pem + cert_pem)
    (certs_dir / "mitmproxy-ca-cert.pem").write_bytes(cert_pem)

    proxy_shared = tmp_path / "proxy_shared"
    proxy_shared.mkdir()

    upstream = EgressProxyConfig.from_env()
    binds: list[str] = [f"{certs_dir}:/certs:ro"]
    if upstream and upstream.ca_bundle:
        shutil.copy2(upstream.ca_bundle, proxy_shared / "upstream_ca.pem")
        binds.append(f"{proxy_shared / 'upstream_ca.pem'}:/shared/upstream_ca.pem:ro")

    proxy_cmd = _build_mitmproxy_cmd(upstream)

    host_config: dict[str, Any] = {"PortBindings": {f"{_PROXY_LISTEN_PORT}/tcp": [{"HostPort": "0"}]}, "Binds": binds}

    async with aiodocker.Docker() as docker:
        container = await docker.containers.create(
            {
                "Image": _MITMPROXY_IMAGE,
                "Cmd": proxy_cmd,
                "ExposedPorts": {f"{_PROXY_LISTEN_PORT}/tcp": {}},
                "HostConfig": host_config,
            }
        )
        await container.start()
        logger.info("Started mitmproxy container")

        log_file = undeclared_outputs_dir() / "mitmproxy.log"

        try:
            info = await container.show()
            host_port = int(info["NetworkSettings"]["Ports"][f"{_PROXY_LISTEN_PORT}/tcp"][0]["HostPort"])

            await _wait_for_proxy_ready("127.0.0.1", host_port)
            logger.info("mitmproxy ready on port %d", host_port)

            yield MitmproxyFixture(
                url=f"http://{_PROXY_USERNAME}:{_PROXY_PASSWORD}@127.0.0.1:{host_port}",
                port=host_port,
                ca_cert_pem=cert_pem,
                log_file=log_file,
            )

        finally:
            proxy_logs = "".join(await container.log(stdout=True, stderr=True))
            log_file.parent.mkdir(parents=True, exist_ok=True)
            log_file.write_text(proxy_logs)

            await container.delete(force=True)
