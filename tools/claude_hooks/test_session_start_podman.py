"""Podman integration tests for session_start hook.

Split from test_session_start.py because podman needs mount/networking capabilities
blocked by Bazel's linux-sandbox and RBE (requires local=True).
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest
import pytest_bazel

from tools.claude_hooks.testing import shell_helpers
from tools.claude_hooks.testing.fixtures import MockEgressProxyFixture, collect_supervisor_logs
from tools.claude_hooks.testing.session_start_helpers import IsolatedDirs, run_session_start_hook, setup_hook_env

# Register fixtures from modules (pytest-native, no direct name import needed)
pytest_plugins = ["tools.claude_hooks.testing.fixtures", "tools.claude_hooks.testing.session_start_helpers"]


def _extract_docker_host_socket(env_file: Path) -> Path:
    """Extract socket path from DOCKER_HOST in env file.

    The env file contains export statements like:
        export DOCKER_HOST="unix:///tmp/claude-podman-abc123.sock"
    """
    env_content = env_file.read_text()
    assert "DOCKER_HOST" in env_content, "DOCKER_HOST not set in env file"

    match = re.search(r'DOCKER_HOST="?unix://([^"\s]+)"?', env_content)
    assert match, f"Could not extract DOCKER_HOST socket path from env file:\n{env_content}"
    return Path(match.group(1))


class TestPodmanIntegration:
    """E2E tests for podman integration with session start hook.

    These tests verify that podman is properly configured and can run containers
    after the session start hook runs. Config and socket use isolated paths
    (~/.cache/claude-hooks/podman/).
    """

    @pytest.fixture
    def podman_hook_env(
        self, monkeypatch: pytest.MonkeyPatch, isolated_dirs: IsolatedDirs, mock_egress_proxy: MockEgressProxyFixture
    ) -> None:
        """Set up environment for running session start hook WITH podman enabled."""
        setup_hook_env(monkeypatch, isolated_dirs, mock_egress_proxy.proxy, container_runtime="podman")

    async def test_podman_can_run_container(
        self, isolated_dirs: IsolatedDirs, podman_hook_env: None, mock_egress_proxy: MockEgressProxyFixture
    ) -> None:
        """Verify podman service starts and can run a container after session start hook.

        Runs podman through the MockEgressProxy to verify the full proxy chain works,
        including CA certificate configuration for container registry pulls.
        """
        result = await run_session_start_hook(isolated_dirs.project)

        assert result.returncode == 0, "Hook failed with non-zero exit code"

        socket_path = _extract_docker_host_socket(isolated_dirs.env_file)
        assert socket_path.exists(), f"Podman socket not created at {socket_path}"

        # Collect supervisor logs (including podman daemon) for CI debugging
        supervisor_dir = isolated_dirs.env_file.parent / "supervisor"
        collect_supervisor_logs(supervisor_dir)

        # Verify we can run podman hello-world through the proxy
        # The gVisor annotation is auto-applied via containers.conf
        # Run through env file to pick up SSL_CERT_FILE for TLS proxy CA
        async with asyncio.timeout(120):
            podman_result = await shell_helpers.run_with_env_file(
                command="podman run --rm docker.io/library/hello-world",
                env_file=isolated_dirs.env_file,
                cwd=isolated_dirs.project,
                check=False,
            )

        # Include proxy stats in failure message for debugging
        proxy = mock_egress_proxy.proxy
        proxy_stats = (
            f"\nProxy stats: {proxy.stats.total_connections} total, "
            f"{proxy.stats.successful_connections} success, "
            f"{proxy.stats.failed_connections} failed"
        )
        if proxy.stats.errors:
            proxy_stats += f"\nProxy errors: {proxy.stats.errors[-5:]}"

        assert podman_result.returncode == 0, (
            f"Podman run failed:\nstdout: {podman_result.stdout}\nstderr: {podman_result.stderr}{proxy_stats}"
        )
        assert "Hello from Docker" in podman_result.stdout, (
            f"Expected 'Hello from Docker' in output:\n{podman_result.stdout}{proxy_stats}"
        )


if __name__ == "__main__":
    pytest_bazel.main()
