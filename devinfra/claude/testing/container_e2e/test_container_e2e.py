"""Container E2E test: build wheel, install in container, run hook, bazel build through proxy.

This test verifies the full wheel packaging and session start flow in an isolated
Docker container with enforced network isolation (--internal Docker network prevents
all external connectivity).

Architecture:
    Host side:
        - MockEgressProxy on 127.0.0.1 (TLS-intercepting + plain HTTP, requires auth)
        - Builds the ducktape wheel via Bazel
        - Pulls e2e-container image from GHCR (python:3.13-slim + git + JDK)
        - Creates Docker container on --internal network
        - Drives test steps via docker exec calls

    Container side (via docker exec):
        - Installs ducktape wheel (pip through proxy)
        - Runs claude-hook (session start hook) which sets up:
          auth proxy, supervisor, bazel wrapper, CA bundles, env file
        - Runs bazel build through the full proxy chain
"""

import json
import logging
import os
import shlex
import shutil
from pathlib import Path
from typing import Any

import aiodocker
import pytest
import pytest_bazel

from devinfra.claude.auth_proxy.setup import SSL_CA_ENV_VARS, SYSTEM_CA_BUNDLES
from devinfra.claude.auth_proxy.vars import PROXY_ENV_VARS
from devinfra.claude.testing.mock_egress_proxy import EgressProxyConfig, MockEgressProxy
from util.bazel.runfiles import get_required_path
from util.testing.undeclared_outputs import undeclared_outputs_dir

logger = logging.getLogger(__name__)

# Rlocation for the ducktape wheel (built by //:wheel)
_WHEEL_RLOCATION = "_main/ducktape-0.1.0-py3-none-any.whl"

# Rlocation for a file in the test workspace (used to derive directory path)
_TEST_WORKSPACE_MODULE = "_main/devinfra/claude/testdata/test_workspace/MODULE.bazel"

# GHCR image for the e2e test container (built by e2e-container-image.yml CI workflow)
_E2E_IMAGE = "ghcr.io/agentydragon/e2e-container:latest"

# Container name prefix
_CONTAINER_NAME = "ducktape-container-e2e"

# Session ID used inside the container (determines log directory path)
_SESSION_ID = "container-e2e-test"

_ENV_FILE = f"/root/.claude/session-env/{_SESSION_ID}/sessionstart-hook-0.sh"


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
) -> tuple[int, str, str]:
    """Run a command in the container via docker exec.

    Returns (exit_code, stdout, stderr). Raises AssertionError if check=True
    and the command fails.
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
        if chunk.stream == 1:  # stdout
            stdout_buf.extend(data)
        elif chunk.stream == 2:  # stderr
            stderr_buf.extend(data)

    inspect_result = await exec_obj.inspect()
    exit_code = inspect_result.get("ExitCode", -1)

    stdout_str = stdout_buf.decode(errors="replace")
    stderr_str = stderr_buf.decode(errors="replace")

    if check and exit_code != 0:
        raise AssertionError(f"Command {cmd} failed (rc={exit_code}):\nstdout:\n{stdout_str}\nstderr:\n{stderr_str}")

    return exit_code, stdout_str, stderr_str


@pytest.fixture
def wheel_path() -> Path:
    """Resolve the built ducktape wheel from runfiles."""
    return get_required_path(_WHEEL_RLOCATION)


@pytest.fixture
def test_workspace_path() -> Path:
    """Resolve the test workspace directory from runfiles."""
    return get_required_path(_TEST_WORKSPACE_MODULE).parent


async def test_container_e2e(tmp_path: Path, wheel_path: Path, test_workspace_path: Path) -> None:
    """Full E2E: install wheel in container, run hook, bazel build through proxy."""
    async with aiodocker.Docker() as docker:
        await _ensure_image(docker, _E2E_IMAGE)

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

            container_name = f"{_CONTAINER_NAME}-{os.getpid()}"

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
            # Proxy configuration — all proxy vars point to the mock egress proxy
            for var in PROXY_ENV_VARS:
                env[var] = proxy_url
            # SSL CA configuration — point to the combined CA inside the container
            for var in SSL_CA_ENV_VARS:
                env[var] = "/certs/combined_ca.pem"

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

            binds = [
                f"{staged_wheel}:/wheel/ducktape-0.1.0-py3-none-any.whl:ro",
                f"{mock_ca_path}:/certs/mock_ca.pem:ro",
                f"{combined_ca_path}:/certs/combined_ca.pem:ro",
                f"{staged_workspace}:/project/test_workspace:ro",
                f"{session_logs_dir}:/root/.claude/session-env/{_SESSION_ID}",
            ]

            container_config = {
                "Image": _E2E_IMAGE,
                "Env": [f"{k}={v}" for k, v in env.items()],
                "Cmd": ["sleep", "infinity"],
                "HostConfig": {"NetworkMode": "host", "Binds": binds},
            }

            logger.info("Creating container: %s", container_name)
            container = await docker.containers.create(
                container_config,  # type: ignore[arg-type]
                name=container_name,
            )

            try:
                await container.start()
                logger.info("Started container %s", container_name)

                # Create project dir with .git (needed for pre-commit install)
                await _exec(container, ["mkdir", "-p", "/project/.git"])

                # Install ducktape wheel
                logger.info("Installing wheel")
                await _exec(
                    container, ["pip", "install", "--break-system-packages", "/wheel/ducktape-0.1.0-py3-none-any.whl"]
                )

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
                hook_rc, hook_stdout, hook_stderr = await _exec(
                    container, ["bash", "-c", f"echo {shlex.quote(hook_input)} | claude-hook"], check=False
                )
                logger.info("Hook stdout: %s", hook_stdout)
                logger.info("Hook stderr: %s", hook_stderr)

                if hook_rc != 0:
                    # Dump daemon logs for debugging
                    daemon_log_path = f"/root/.claude/session-env/{_SESSION_ID}/hook-daemon/daemon.log"
                    daemon_err_path = f"/root/.claude/session-env/{_SESSION_ID}/hook-daemon/daemon.err.log"
                    for log_path in [daemon_log_path, daemon_err_path]:
                        rc, log_content, _ = await _exec(container, ["cat", log_path], check=False)
                        if rc == 0:
                            logger.info("=== %s:\n%s", log_path, log_content)
                    raise AssertionError(
                        f"claude-hook failed (rc={hook_rc}):\nstdout:\n{hook_stdout}\nstderr:\n{hook_stderr}"
                    )

                # Run bazel build through the proxy chain
                logger.info("Running bazel build")
                bazel_cmd = f"source {_ENV_FILE} && bazel --output_base=/tmp/bazel_output_base build //:hello"
                await _exec(container, ["bash", "-c", bazel_cmd], workdir="/project/test_workspace")

                logger.info("Container E2E test PASSED")

                # Save container logs for debugging
                stdout = "".join(await container.log(stdout=True, stderr=False))
                stderr = "".join(await container.log(stdout=False, stderr=True))
                _save_output("container-stdout.log", stdout)
                _save_output("container-stderr.log", stderr)

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
                await container.delete(force=True)
                # Session logs are already on host via bind-mount; just clean up
                # dangling symlinks (e.g. bin/bazelisk) that Bazel would reject
                _cleanup_dangling_symlinks(session_logs_dir)


if __name__ == "__main__":
    pytest_bazel.main()
