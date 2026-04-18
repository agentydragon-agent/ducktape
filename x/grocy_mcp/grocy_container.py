"""Grocy container bring-up used by the eval CLI and the pytest fixtures."""

from __future__ import annotations

import logging
import os
import tempfile
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

import httpx
from testcontainers.core.container import DockerContainer

from third_party.containers.rlocations import GROCY
from util.oci import load_oci_image
from x.grocy_mcp.config import ServerSettings

logger = logging.getLogger(__name__)

# Set GROCY_MCP_HOST_NETWORK=1 to run the container with --network=host and
# talk to it directly at 127.0.0.1:80. Required on gvisor sandboxes where
# IPv4 forwarding is off, so Docker port publishing is a no-op and
# testcontainers' get_exposed_port(80) never resolves. Outside the sandbox
# (normal test runs) this is unset and behaviour is unchanged.
_HOST_NETWORK_ENV = "GROCY_MCP_HOST_NETWORK"


def _host_network_enabled() -> bool:
    return os.environ.get(_HOST_NETWORK_ENV) == "1"


def make_settings(grocy_url: str) -> ServerSettings:
    """Settings for a Grocy test instance: direct HTTP, no Authentik outpost."""
    return ServerSettings(grocy_url=grocy_url)


@contextmanager
def grocy_custom_init_dir() -> Generator[str]:
    """Yield a tempdir containing an init script that strips IPv6 listen directives.

    LinuxServer s6-overlay runs scripts in /custom-cont-init.d/ after
    migrations (which generate the nginx config) but before services start.
    The dir is bind-mounted read-only into the container and removed on exit
    so repeated calls (e.g. from the eval CLI) don't leak under /tmp.
    """
    with tempfile.TemporaryDirectory(prefix="grocy-custom-init-") as d:
        script = Path(d) / "disable-ipv6.sh"
        script.write_text(
            "#!/bin/bash\n"
            "echo 'disable-ipv6: patching nginx configs'\n"
            "sed -i '/listen \\[/d' /config/nginx/site-confs/*.conf\n"
            "echo 'disable-ipv6: done, resulting config:'\n"
            "cat /config/nginx/site-confs/default.conf\n"
        )
        script.chmod(0o755)
        yield d


def configure_grocy_container(container: DockerContainer, *, init_dir: str, data_dir: Path | None) -> None:
    """Apply the env / volume / port config every Grocy test container needs.

    `init_dir` is the tempdir from `grocy_custom_init_dir()`; it must stay
    alive until the container exits. If `data_dir` is provided, it's
    bind-mounted to Grocy's `/config/data`, so the SQLite DB lives at
    `data_dir/grocy.db` on the host throughout the run — no post-hoc copy
    needed. LinuxServer chowns the mount point on startup.
    """
    if _host_network_enabled():
        container.with_kwargs(network_mode="host")
    else:
        container.with_exposed_ports(80)
    container.with_env("PUID", "1000")
    container.with_env("PGID", "1000")
    container.with_env("TZ", "UTC")
    container.with_env("GROCY_MODE", "production")
    container.with_env("GROCY_DISABLE_AUTH", "true")
    container.with_volume_mapping(init_dir, "/custom-cont-init.d", "ro")
    if data_dir is not None:
        data_dir.mkdir(parents=True, exist_ok=True)
        # LinuxServer's s6-init does `chown -R abc:abc /config` which, on
        # some filesystems (gvisor overlay, tmpfs bind mounts owned by root
        # with restrictive parent perms), silently fails for bind-mounted
        # paths. Pre-chown the host dir to match PUID/PGID so the copy of
        # config-dist.php into /config/data/config.php actually lands;
        # otherwise Grocy serves an HTML error about the missing config.
        # Best-effort: not root, read-only FS, etc. all fall through.
        try:
            os.chown(data_dir, 1000, 1000)
        except OSError:
            logger.debug("best-effort chown failed for %s", data_dir, exc_info=True)
        # testcontainers defaults `with_volume_mapping` to read-only, which
        # would silently break LinuxServer's config.php copy. Force rw.
        container.with_volume_mapping(str(data_dir), "/config/data", "rw")


def grocy_url(container: DockerContainer) -> str:
    if _host_network_enabled():
        return "http://127.0.0.1:80"
    host = container.get_container_host_ip()
    port = container.get_exposed_port(80)
    return f"http://{host}:{port}"


def wait_for_grocy_ready(container: DockerContainer, *, timeout_s: float = 90) -> None:
    """Poll until Grocy's DB migrations have run and `/api/system/info` is live.

    Grocy runs migrations *lazily on the first HTML request*: hitting any
    `/api/*` endpoint on a fresh container returns HTTP 500
    ``{"error_message":"no such table: users"}`` indefinitely until something
    triggers migrations. ``GET /`` (which 302s to ``/stockoverview``) does the
    trick. After that, ``/api/system/info`` transitions from 500 to 200 with
    a JSON body containing ``grocy_version`` — we poll for that specifically
    rather than just HTTP 200, because intermediate states can still be 200
    with an error body.
    """
    base_url = grocy_url(container)
    deadline = time.monotonic() + timeout_s
    last_err = ""
    while time.monotonic() < deadline:
        try:
            httpx.get(f"{base_url}/", timeout=10)
            r = httpx.get(f"{base_url}/api/system/info", timeout=10)
            if r.status_code == 200:
                try:
                    data = r.json()
                except ValueError:
                    last_err = f"200 but non-JSON body: {r.text[:200]}"
                else:
                    if "grocy_version" in data:
                        logger.info("Grocy ready at %s (v%s)", base_url, data["grocy_version"])
                        return
                    last_err = f"200 but no grocy_version (body={data!r})"
            else:
                last_err = f"HTTP {r.status_code}: {r.text[:200]}"
        except httpx.RequestError as e:
            # Includes ConnectError, ReadError, RemoteProtocolError, plus
            # ConnectTimeout / ReadTimeout that the per-request timeout=10s
            # may produce while Grocy is still initializing.
            last_err = f"{type(e).__name__}: {e}"
        time.sleep(2)
    raise TimeoutError(f"Grocy did not become ready at {base_url} within {timeout_s}s. Last: {last_err}")


@contextmanager
def run_grocy_container(*, data_dir: Path | None = None) -> Generator[DockerContainer]:
    """Run a fresh Grocy container with auth disabled; yield it once ready."""
    load_oci_image(GROCY)
    with grocy_custom_init_dir() as init_dir:
        container = DockerContainer(GROCY.tag)
        configure_grocy_container(container, init_dir=init_dir, data_dir=data_dir)
        with container:
            wait_for_grocy_ready(container)
            yield container
