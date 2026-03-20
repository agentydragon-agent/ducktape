"""Container E2E test: build wheel, install in container, run hook, bazel build through proxy.

This test verifies the full wheel packaging and session start flow in an isolated
Docker container with enforced network isolation (broken DNS forces all traffic
through the mock egress proxy).

Architecture:
    Host side:
        - MockEgressProxy on 127.0.0.1 (TLS-intercepting + plain HTTP, requires auth)
        - Builds the ducktape wheel via Bazel
        - Pulls e2e-container image from GHCR (python:3.13-slim + git + JDK)
        - Creates Docker container with --network=host and broken DNS

    Container side (run_in_container.py):
        - Installs ducktape wheel (pip through proxy)
        - Runs claude-hook (session start hook) which sets up:
          auth proxy, supervisor, bazel wrapper, CA bundles, env file
        - Runs bazel build through the full proxy chain
"""

import asyncio
import logging
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import pytest_bazel

from devinfra.claude.auth_proxy.setup import SSL_CA_ENV_VARS, SYSTEM_CA_BUNDLES
from devinfra.claude.auth_proxy.vars import PROXY_ENV_VARS
from devinfra.claude.testing.mock_egress_proxy import EgressProxyConfig, MockEgressProxy
from util.bazel.runfiles import get_required_path
from util.net import pick_free_port
from util.testing.undeclared_outputs import undeclared_outputs_dir

logger = logging.getLogger(__name__)

# Rlocation for the ducktape wheel (built by //:wheel)
_WHEEL_RLOCATION = "_main/ducktape-0.1.0-py3-none-any.whl"

# Rlocation for the container-side script
_RUN_IN_CONTAINER_RLOCATION = "_main/devinfra/claude/testing/container_e2e/run_in_container.py"

# Rlocation for a file in the test workspace (used to derive directory path)
_TEST_WORKSPACE_MODULE = "_main/devinfra/claude/testdata/test_workspace/MODULE.bazel"

# GHCR image for the e2e test container (built by e2e-container-image.yml CI workflow)
_E2E_IMAGE = "ghcr.io/agentydragon/e2e-container:latest"

# Container name prefix
_CONTAINER_NAME = "ducktape-container-e2e"


def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a docker command."""
    cmd = ["docker", *args]
    return subprocess.run(cmd, check=check, capture_output=True, text=True)


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


@pytest.fixture
def docker_available() -> None:
    """Skip test if Docker is not available."""
    result = _docker("info", check=False)
    if result.returncode != 0:
        pytest.skip("Docker not available")


@pytest.fixture
def e2e_image(docker_available: None) -> str:
    """Pull the pre-built e2e test container image from GHCR."""
    # Reuse if already present locally
    result = _docker("image", "inspect", _E2E_IMAGE, check=False)
    if result.returncode == 0:
        logger.info("E2E image %s already exists, reusing", _E2E_IMAGE)
        return _E2E_IMAGE

    logger.info("Pulling E2E image %s", _E2E_IMAGE)
    _docker("pull", _E2E_IMAGE)
    return _E2E_IMAGE


@pytest.fixture
def wheel_path() -> Path:
    """Resolve the built ducktape wheel from runfiles."""
    return get_required_path(_WHEEL_RLOCATION)


@pytest.fixture
def container_script_path() -> Path:
    """Resolve the run_in_container.py script from runfiles."""
    return get_required_path(_RUN_IN_CONTAINER_RLOCATION)


@pytest.fixture
def test_workspace_path() -> Path:
    """Resolve the test workspace directory from runfiles."""
    return get_required_path(_TEST_WORKSPACE_MODULE).parent


async def test_container_e2e(
    tmp_path: Path, e2e_image: str, wheel_path: Path, container_script_path: Path, test_workspace_path: Path
) -> None:
    """Full E2E: install wheel in container, run hook, bazel build through proxy."""
    # Start mock egress proxy — handles both CONNECT (TLS MITM) and plain HTTP
    async with MockEgressProxy(
        listen_port=0,
        listen_address="127.0.0.1",
        username="proxy_user",
        password="test_jwt_token",
        upstream_proxy=EgressProxyConfig.from_env(),
    ) as proxy:
        logger.info("MockEgressProxy listening on port %d", proxy.port)

        # Write mock CA cert to a file the container can access
        mock_ca_path = tmp_path / "mock_ca.pem"
        mock_ca_path.write_bytes(proxy.ca_cert_pem)

        # Create combined CA bundle (system CAs + mock proxy CA)
        system_ca_path = next((p for p in SYSTEM_CA_BUNDLES if p.exists()), None)
        combined_ca_path = tmp_path / "combined_ca.pem"
        system_cas = system_ca_path.read_bytes() if system_ca_path else b""
        combined_ca_path.write_bytes(system_cas + b"\n" + proxy.ca_cert_pem)

        # With --network=host, the container shares the host network namespace
        # so localhost:port works directly
        proxy_url = f"http://proxy_user:test_jwt_token@127.0.0.1:{proxy.port}"

        # Build docker run command
        container_name = f"{_CONTAINER_NAME}-{os.getpid()}"

        env_args: list[str] = []

        # Web mode trigger
        env_args += ["-e", "CLAUDE_CODE_REMOTE=true"]

        # Project and env file paths (inside container)
        env_args += ["-e", "CLAUDE_PROJECT_DIR=/project"]
        env_args += ["-e", "CLAUDE_ENV_FILE=/root/.claude/session-env/container-e2e-test/sessionstart-hook-0.sh"]

        # Isolated dirs
        env_args += ["-e", "HOME=/root"]
        env_args += ["-e", "XDG_CACHE_HOME=/cache"]
        env_args += ["-e", "XDG_CONFIG_HOME=/config"]
        env_args += ["-e", "XDG_RUNTIME_DIR=/run/user/0"]

        # Pick isolated ports for supervisor and auth proxy (avoid conflicts
        # with host services when using --network=host)
        container_supervisor_port = pick_free_port()
        container_auth_proxy_port = pick_free_port()

        # Hook settings
        env_args += ["-e", "DUCKTAPE_CLAUDE_HOOKS_INSTALL_BAZELISK=true"]
        env_args += ["-e", "DUCKTAPE_CLAUDE_HOOKS_INSTALL_MKCERT=false"]
        env_args += ["-e", "DUCKTAPE_CLAUDE_HOOKS_CONTAINER_RUNTIME=none"]
        env_args += ["-e", f"DUCKTAPE_CLAUDE_HOOKS_SUPERVISOR_PORT={container_supervisor_port}"]
        env_args += ["-e", f"DUCKTAPE_CLAUDE_HOOKS_AUTH_PROXY_PORT={container_auth_proxy_port}"]

        # Proxy configuration - all proxy vars point to the mock egress proxy
        for var in PROXY_ENV_VARS:
            env_args += ["-e", f"{var}={proxy_url}"]

        # SSL CA configuration - point to the combined CA inside the container
        for var in SSL_CA_ENV_VARS:
            env_args += ["-e", f"{var}=/certs/combined_ca.pem"]

        # Mock CA path (used by _extract_proxy_ca in proxy_setup)
        env_args += ["-e", "ANTHROPIC_CA_PATH=/certs/mock_ca.pem"]

        # Wheel path inside container
        env_args += ["-e", "WHEEL_PATH=/wheel/ducktape-0.1.0-py3-none-any.whl"]

        # Copy files to a staging directory so Docker can mount real files
        # (runfiles may be symlinks that Docker cannot resolve in gVisor)
        staging = tmp_path / "staging"
        staging.mkdir()
        staged_wheel = staging / "ducktape-0.1.0-py3-none-any.whl"
        shutil.copy2(wheel_path, staged_wheel)
        staged_script = staging / "run_in_container.py"
        shutil.copy2(container_script_path, staged_script)
        staged_workspace = staging / "test_workspace"
        shutil.copytree(test_workspace_path, staged_workspace)

        # Bind-mount the session dir so logs land directly in undeclared outputs
        session_logs_dir = undeclared_outputs_dir() / "container-e2e" / "session-logs"
        session_logs_dir.mkdir(parents=True, exist_ok=True)

        # Volume mounts
        mount_args = [
            "-v",
            f"{staged_wheel}:/wheel/ducktape-0.1.0-py3-none-any.whl:ro",
            "-v",
            f"{staged_script}:/run_in_container.py:ro",
            "-v",
            f"{mock_ca_path}:/certs/mock_ca.pem:ro",
            "-v",
            f"{combined_ca_path}:/certs/combined_ca.pem:ro",
            "-v",
            f"{staged_workspace}:/testdata/test_workspace:ro",
            "-v",
            f"{session_logs_dir}:/root/.claude/session-env/container-e2e-test",
        ]

        # Network isolation: --network=host for gVisor compatibility, but DNS is
        # broken inside the container (resolv.conf overwritten with unreachable
        # nameserver). This forces tools to use the proxy for CONNECT tunneling
        # (CONNECT doesn't need client-side DNS resolution). Plain HTTP requests
        # (like pip install) also go through the proxy which resolves DNS on the
        # host side.
        network_args = ["--network=host"]

        docker_cmd = [
            "docker",
            "run",
            "--name",
            container_name,
            *env_args,
            *mount_args,
            *network_args,
            e2e_image,
            "bash",
            "-c",
            # git + JDK are pre-installed in the e2e image.
            # Break DNS to enforce proxy usage, then run the test.
            "mkdir -p /project/.git /cache /config /run/user/0 && "
            "echo 'nameserver 192.0.2.1' > /etc/resolv.conf && "
            "python /run_in_container.py",
        ]

        logger.info("Starting container: %s", container_name)

        try:
            proc = await asyncio.create_subprocess_exec(
                *docker_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=300)
            except TimeoutError:
                # Kill the container on timeout
                _docker("kill", container_name, check=False)
                proc.kill()
                await proc.wait()
                raise

            stdout = stdout_bytes.decode() if stdout_bytes else ""
            stderr = stderr_bytes.decode() if stderr_bytes else ""

            # Save outputs for debugging
            _save_output("container-stdout.log", stdout)
            _save_output("container-stderr.log", stderr)

            assert proc.returncode == 0, (
                f"Container E2E test failed (rc={proc.returncode}):\nstdout:\n{stdout}\nstderr:\n{stderr}"
            )

            # Verify the mock proxy actually saw traffic
            assert proxy.stats.total_connections > 0, (
                "Mock egress proxy received no connections - network isolation may not be working"
            )
            logger.info(
                "Container E2E passed: %d proxy connections, %d successful",
                proxy.stats.total_connections,
                proxy.stats.successful_connections,
            )

        finally:
            _docker("rm", "-f", container_name, check=False)
            # Session logs are already on host via bind-mount; just clean up
            # dangling symlinks (e.g. bin/bazelisk) that Bazel would reject
            _cleanup_dangling_symlinks(session_logs_dir)


if __name__ == "__main__":
    pytest_bazel.main()
