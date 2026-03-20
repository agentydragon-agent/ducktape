"""Container E2E test: build wheel, install in container, run hook, bazel build through proxy.

This test verifies the full wheel packaging and session start flow in an isolated
Docker container with enforced network isolation (--internal Docker network prevents
all external connectivity).

Architecture:
    Host side:
        - Builds the ducktape wheel via Bazel
        - Builds MockEgressProxy OCI image via Bazel and loads it into Docker
        - Pulls e2e-container image from GHCR (python:3.13-slim + git + JDK)
        - Creates two Docker networks:
          - e2e-proxy (bridge): proxy container has internet access
          - e2e-isolated (internal bridge): test container ↔ proxy container only
        - MockEgressProxy runs as a container on both networks
        - Drives test steps via docker exec calls

    Container side (via docker exec):
        - Installs ducktape wheel (pip through proxy → MockEgressProxy container)
        - Runs claude-hook (session start hook) which sets up:
          auth proxy, supervisor, bazel wrapper, CA bundles, env file
        - Runs bazel build through the full proxy chain
"""

import asyncio
import json
import logging
import os
import shlex
import shutil
import urllib.parse
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import aiodocker
import pytest
import pytest_bazel

from devinfra.claude.auth_proxy.setup import SSL_CA_ENV_VARS, SYSTEM_CA_BUNDLES
from devinfra.claude.auth_proxy.vars import PROXY_ENV_VARS
from devinfra.claude.testing.mock_egress_proxy import EgressProxyConfig
from util.bazel.runfiles import get_required_path
from util.oci import load_bazel_image
from util.testing.undeclared_outputs import undeclared_outputs_dir

logger = logging.getLogger(__name__)

# Docker exec stream type codes (same as mcp_infra/exec/docker/container_session.py)
STREAM_TYPE_STDOUT = 1
STREAM_TYPE_STDERR = 2

# Rlocation for the ducktape wheel (built by //:wheel)
_WHEEL_RLOCATION = "_main/ducktape-0.1.0-py3-none-any.whl"

# Rlocation for a file in the test workspace (used to derive directory path)
_TEST_WORKSPACE_MODULE = "_main/devinfra/claude/testdata/test_workspace/MODULE.bazel"

# GHCR image for the e2e test container (built by e2e-container-image.yml CI workflow)
_E2E_IMAGE = "ghcr.io/agentydragon/e2e-container:latest"

# OCI image for the mock egress proxy container
_MOCK_PROXY_IMAGE = "mock-egress-proxy:latest"
_MOCK_PROXY_LOAD_SCRIPT = "devinfra/claude/testing/mock_egress_proxy_load/load.sh"

# Container name prefix
_CONTAINER_NAME = "ducktape-container-e2e"

# Session ID used inside the container (determines log directory path)
_SESSION_ID = "container-e2e-test"

_ENV_FILE = f"/root/.claude/session-env/{_SESSION_ID}/sessionstart-hook-0.sh"

# Port the proxy listens on inside its container
_PROXY_LISTEN_PORT = 8080

# Timeout for proxy container readiness (seconds)
_PROXY_READY_TIMEOUT = 60


def _save_output(name: str, content: str) -> None:
    """Save content to undeclared test outputs."""
    out_dir = undeclared_outputs_dir() / "container-e2e"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / name).write_text(content)


def _cleanup_dangling_symlinks(directory: Path) -> None:
    """Remove dangling symlinks — Bazel rejects them in output trees."""
    for p in directory.rglob("*"):
        if p.is_symlink() and not p.exists():
            p.unlink()


async def _ensure_image(docker: aiodocker.Docker, image: str) -> None:
    """Pull the image if not already present locally."""
    try:
        await docker.images.inspect(image)
        logger.info("E2E image %s already exists, reusing", image)
    except aiodocker.DockerError as e:
        if e.status != 404:
            raise
        logger.info("Pulling E2E image %s", image)
        await docker.pull(image)


async def _exec(
    container: aiodocker.containers.DockerContainer, cmd: list[str], *, workdir: str | None = None, check: bool = True
) -> tuple[int, bytes, bytes]:
    """Run a command in the container via docker exec.

    Returns (exit_code, stdout, stderr) as raw bytes. Raises AssertionError
    if check=True and the command fails.
    """
    exec_obj = await container.exec(cmd, stdout=True, stderr=True, stdin=False, tty=False, workdir=workdir or "")
    stream: Any = exec_obj.start()

    stdout_buf = bytearray()
    stderr_buf = bytearray()
    while True:
        chunk = await stream.read_out()
        if chunk is None:
            break
        data = chunk.data if isinstance(chunk.data, bytes) else chunk.data.encode()
        if chunk.stream == STREAM_TYPE_STDOUT:
            stdout_buf.extend(data)
        elif chunk.stream == STREAM_TYPE_STDERR:
            stderr_buf.extend(data)

    inspect_result = await exec_obj.inspect()
    exit_code = inspect_result.get("ExitCode", -1)

    logger.info("exec %s → rc=%d, stdout=%d bytes, stderr=%d bytes", cmd, exit_code, len(stdout_buf), len(stderr_buf))
    if stdout_buf:
        logger.info("stdout: %s", stdout_buf.decode(errors="replace"))
    if stderr_buf:
        logger.info("stderr: %s", stderr_buf.decode(errors="replace"))

    if check and exit_code != 0:
        raise AssertionError(
            f"Command {cmd} failed (rc={exit_code}):\n"
            f"stdout:\n{stdout_buf.decode(errors='replace')}\n"
            f"stderr:\n{stderr_buf.decode(errors='replace')}"
        )

    return exit_code, bytes(stdout_buf), bytes(stderr_buf)


def _build_upstream_proxy_args(upstream: EgressProxyConfig, gateway_ip: str, proxy_shared: Path) -> list[str]:
    """Build CLI args for upstream proxy configuration.

    Rewrites localhost references to gateway_ip so the proxy container can
    reach host-side services via the bridge network gateway.
    """
    host = upstream.host
    if host in ("localhost", "127.0.0.1"):
        host = gateway_ip

    url = "http://"
    if upstream.username and upstream.password:
        url += f"{urllib.parse.quote(upstream.username)}:{urllib.parse.quote(upstream.password)}@"
    url += f"{host}:{upstream.port}"

    args = ["--upstream-proxy-url", url]

    if upstream.ca_bundle:
        shutil.copy2(upstream.ca_bundle, proxy_shared / "upstream_ca.pem")
        args += ["--upstream-ca-bundle", "/shared/upstream_ca.pem"]

    return args


@pytest.fixture
def wheel_path() -> Path:
    """Resolve the built ducktape wheel from runfiles."""
    return get_required_path(_WHEEL_RLOCATION)


@pytest.fixture
def test_workspace_path() -> Path:
    """Resolve the test workspace directory from runfiles."""
    return get_required_path(_TEST_WORKSPACE_MODULE).parent


@pytest.fixture
def mock_proxy_image() -> str:
    """Load the mock egress proxy OCI image into Docker."""
    return load_bazel_image(_MOCK_PROXY_LOAD_SCRIPT, _MOCK_PROXY_IMAGE)


@pytest.fixture
async def docker_client() -> AsyncGenerator[aiodocker.Docker]:
    """Yield an aiodocker client, closing on teardown."""
    async with aiodocker.Docker() as client:
        yield client


async def test_container_e2e(
    tmp_path: Path, wheel_path: Path, test_workspace_path: Path, mock_proxy_image: str, docker_client: aiodocker.Docker
) -> None:
    """Full E2E: install wheel in container, run hook, bazel build through proxy."""
    await _ensure_image(docker_client, _E2E_IMAGE)

    # Shared directory for proxy ↔ host communication (CA cert, ready signal, stats)
    proxy_shared = tmp_path / "proxy_shared"
    proxy_shared.mkdir()

    # Copy files to a staging directory so Docker can mount real files
    # (runfiles may be symlinks that Docker cannot resolve in gVisor)
    staging = tmp_path / "staging"
    staging.mkdir()
    staged_wheel = staging / "ducktape-0.1.0-py3-none-any.whl"
    shutil.copy2(wheel_path, staged_wheel)
    staged_workspace = staging / "test_workspace"
    shutil.copytree(test_workspace_path, staged_workspace)

    # Bind-mount the session dir so logs land directly in undeclared outputs
    session_logs_dir = undeclared_outputs_dir() / "container-e2e" / "session-logs"
    session_logs_dir.mkdir(parents=True, exist_ok=True)

    pid = os.getpid()
    proxy_net_name = f"e2e-proxy-{pid}"
    isolated_net_name = f"e2e-isolated-{pid}"
    container_name = f"{_CONTAINER_NAME}-{pid}"
    proxy_name = f"{_CONTAINER_NAME}-proxy-{pid}"

    # Create networks
    proxy_net = await docker_client.networks.create({"Name": proxy_net_name, "Driver": "bridge"})
    isolated_net = await docker_client.networks.create(
        {"Name": isolated_net_name, "Driver": "bridge", "Internal": True}
    )

    proxy_container: aiodocker.containers.DockerContainer | None = None
    container: aiodocker.containers.DockerContainer | None = None

    try:
        # Get gateway IP of the proxy network (host is reachable at this IP)
        proxy_net_info = await proxy_net.show()
        gateway_ip = proxy_net_info["IPAM"]["Config"][0]["Gateway"]
        logger.info("Proxy network gateway (host reachable at): %s", gateway_ip)

        # Build proxy container command
        proxy_cmd = [
            "--listen-port",
            str(_PROXY_LISTEN_PORT),
            "--username",
            "proxy_user",
            "--password",
            "test_jwt_token",
            "--ca-output-dir",
            "/shared",
            "--ready-file",
            "/shared/ready",
            "--stats-output-file",
            "/shared/stats.json",
        ]

        # Detect upstream proxy from host environment
        upstream = EgressProxyConfig.from_env()
        if upstream:
            proxy_cmd += _build_upstream_proxy_args(upstream, gateway_ip, proxy_shared)
        else:
            proxy_cmd.append("--no-verify-target-certs")

        # Start proxy container on proxy network (has internet access)
        proxy_container = await docker_client.containers.create(
            {
                "Image": mock_proxy_image,
                "Cmd": proxy_cmd,
                "HostConfig": {"NetworkMode": proxy_net_name, "Binds": [f"{proxy_shared}:/shared"]},
            },
            name=proxy_name,
        )
        await proxy_container.start()
        logger.info("Started proxy container %s", proxy_name)

        # Connect proxy container to the isolated network too
        await isolated_net.connect({"Container": proxy_container._id})

        # Wait for proxy to become ready
        for _ in range(int(_PROXY_READY_TIMEOUT / 0.2)):
            if (proxy_shared / "ready").exists():
                break
            await asyncio.sleep(0.2)
        else:
            # Collect proxy logs for debugging
            try:
                stdout = "".join(await proxy_container.log(stdout=True, stderr=True))
                _save_output("proxy-container.log", stdout)
                logger.error("Proxy container logs:\n%s", stdout)
            except Exception:
                pass
            raise TimeoutError("MockEgressProxy container failed to become ready")

        logger.info("MockEgressProxy container is ready")

        # Read mock CA cert from shared volume
        mock_ca_pem = (proxy_shared / "ca.pem").read_bytes()

        # Create combined CA bundle (system CAs + mock proxy CA)
        system_ca_path = next((p for p in SYSTEM_CA_BUNDLES if p.exists()), None)
        combined_ca_path = tmp_path / "combined_ca.pem"
        system_cas = system_ca_path.read_bytes() if system_ca_path else b""
        combined_ca_path.write_bytes(system_cas + b"\n" + mock_ca_pem)

        mock_ca_path = tmp_path / "mock_ca.pem"
        mock_ca_path.write_bytes(mock_ca_pem)

        # Get proxy container's IP on the isolated network
        proxy_info = await proxy_container.show()
        proxy_ip = proxy_info["NetworkSettings"]["Networks"][isolated_net_name]["IPAddress"]
        logger.info("Proxy container IP on isolated network: %s", proxy_ip)

        # Proxy URL for the test container
        proxy_url = f"http://proxy_user:test_jwt_token@{proxy_ip}:{_PROXY_LISTEN_PORT}"

        # Environment variables
        env = {
            # Web mode trigger
            "CLAUDE_CODE_REMOTE": "true",
            # Project and env file paths (inside container)
            "CLAUDE_PROJECT_DIR": "/project",
            "CLAUDE_ENV_FILE": _ENV_FILE,
            # Hook settings
            "DUCKTAPE_CLAUDE_HOOKS_INSTALL_BAZELISK": "true",
            "DUCKTAPE_CLAUDE_HOOKS_INSTALL_MKCERT": "false",
            "DUCKTAPE_CLAUDE_HOOKS_CONTAINER_RUNTIME": "none",
            # Mock CA path (used by _extract_proxy_ca in proxy_setup)
            "ANTHROPIC_CA_PATH": "/certs/mock_ca.pem",
            # Wheel path inside container
            "WHEEL_PATH": "/wheel/ducktape-0.1.0-py3-none-any.whl",
        }
        # Proxy configuration — all proxy vars point through the proxy container
        for var in PROXY_ENV_VARS:
            env[var] = proxy_url
        # SSL CA configuration — point to the combined CA inside the container
        for var in SSL_CA_ENV_VARS:
            env[var] = "/certs/combined_ca.pem"

        binds = [
            f"{staged_wheel}:/wheel/ducktape-0.1.0-py3-none-any.whl:ro",
            f"{mock_ca_path}:/certs/mock_ca.pem:ro",
            f"{combined_ca_path}:/certs/combined_ca.pem:ro",
            f"{staged_workspace}:/project/test_workspace:ro",
            f"{session_logs_dir}:/root/.claude/session-env/{_SESSION_ID}",
        ]

        # Test container on isolated network only — no direct internet access
        container = await docker_client.containers.create(
            {
                "Image": _E2E_IMAGE,
                "Env": [f"{k}={v}" for k, v in env.items()],
                "Cmd": ["sleep", "infinity"],
                "HostConfig": {"NetworkMode": isolated_net_name, "Binds": binds},
            },
            name=container_name,
        )
        await container.start()
        logger.info("Started test container %s on isolated network", container_name)

        # Verify network isolation — container must not reach the internet directly
        rc, _, _ = await _exec(container, ["bash", "-c", "curl --max-time 3 https://google.com"], check=False)
        assert rc != 0, "Container should have no external internet access on --internal network"
        logger.info("Network isolation verified: container cannot reach internet directly")

        # Create project dir with .git (needed for pre-commit install)
        await _exec(container, ["mkdir", "-p", "/project/.git"])

        # Install ducktape wheel
        # TODO(container-e2e): Install via uv by reading .claude/settings.json
        # hook definition and piping the JSON into sh, instead of raw pip.
        logger.info("Installing wheel")
        await _exec(container, ["pip", "install", "--break-system-packages", "/wheel/ducktape-0.1.0-py3-none-any.whl"])

        # Run session start hook
        logger.info("Running claude-hook (session start)")
        hook_input = json.dumps(
            {
                "hook_event_name": "SessionStart",
                "session_id": _SESSION_ID,
                "cwd": "/project",
                "transcript_path": "/tmp/transcript.json",
                "permission_mode": "default",
                "source": "startup",
                "model": "claude-sonnet-4-6",
            }
        )
        await _exec(container, ["bash", "-c", f"echo {shlex.quote(hook_input)} | claude-hook"])

        # Run bazel build through the proxy chain
        logger.info("Running bazel build")
        bazel_cmd = f"source {_ENV_FILE} && bazel build //:hello"
        await _exec(container, ["bash", "-c", bazel_cmd], workdir="/project/test_workspace")

        # Stop proxy container (SIGTERM triggers stats write)
        await proxy_container.kill(signal="SIGTERM")
        await proxy_container.wait()

        # Verify the mock proxy actually saw traffic
        stats = json.loads((proxy_shared / "stats.json").read_text())
        assert stats["total_connections"] > 0, (
            "Mock egress proxy received no connections - network isolation may not be working"
        )
        logger.info("Proxy stats: %s", stats)

    finally:
        # Save container logs before cleanup
        if container is not None:
            try:
                stdout = "".join(await container.log(stdout=True, stderr=False))
                stderr = "".join(await container.log(stdout=False, stderr=True))
                _save_output("container-stdout.log", stdout)
                _save_output("container-stderr.log", stderr)
            except Exception:
                logger.warning("Failed to collect container logs", exc_info=True)
            await container.delete(force=True)

        if proxy_container is not None:
            try:
                stdout = "".join(await proxy_container.log(stdout=True, stderr=True))
                _save_output("proxy-container.log", stdout)
            except Exception:
                logger.warning("Failed to collect proxy container logs", exc_info=True)
            await proxy_container.delete(force=True)

        # Disconnect containers from networks before deleting networks
        # (force=True on delete already stops containers, but network cleanup
        # needs containers disconnected first)
        try:
            await isolated_net.delete()
        except Exception:
            logger.warning("Failed to delete isolated network", exc_info=True)
        try:
            await proxy_net.delete()
        except Exception:
            logger.warning("Failed to delete proxy network", exc_info=True)

        # Session logs are already on host via bind-mount; just clean up
        # dangling symlinks (e.g. bin/bazelisk) that Bazel would reject
        _cleanup_dangling_symlinks(session_logs_dir)


if __name__ == "__main__":
    pytest_bazel.main()
