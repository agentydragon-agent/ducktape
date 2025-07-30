"""Docker management for coding agent execution in isolated containers."""

import os
import shutil
import subprocess
from contextlib import contextmanager, suppress
from pathlib import Path

import docker


class DockerManager:
    """Manages Docker wrapper setup for coding agent execution."""

    def __init__(self):
        """Initialize DockerManager and locate Docker binary."""
        self._original_path = os.environ.get("PATH", "")
        self._docker_path = self._find_docker()
        self._docker_client = docker.from_env()

    def _find_docker(self) -> str:
        docker_path = shutil.which("docker", path=self._original_path)
        if docker_path is None:
            raise RuntimeError("Docker is required")
        return docker_path

    @contextmanager
    def wrapper(self, base_dir: Path, wrapper_script_path: Path):
        """Set up Docker wrapper script with automatic cleanup.

        Args:
            base_dir: Base directory for the run
            wrapper_script_path: Path to the docker_claude_wrapper.sh script

        Yields:
            str: Isolated PATH containing only wrapper and essential binaries
        """
        wrapper_dir = base_dir / "bin"
        wrapper_dir.mkdir(parents=True, exist_ok=True)
        wrapper_script = wrapper_dir / "claude"

        # Copy the external Docker wrapper script
        if not wrapper_script_path.exists():
            raise FileNotFoundError(
                f"Docker wrapper script not found: {wrapper_script_path}",
            )

        try:
            # Find docker binary path
            docker_path = shutil.which("docker", path=self._original_path)
            if not docker_path:
                raise RuntimeError("Docker binary not found in PATH")

            # Generate wrapper script inline
            wrapper_content = f"""#!/bin/sh
# Docker wrapper for Claude CLI using long-running containers
if [ -z "$CLAUDE_CONTAINER_ID" ]; then
    echo "ERROR: CLAUDE_CONTAINER_ID environment variable not set" >&2
    exit 1
fi
exec {docker_path} exec -i "$CLAUDE_CONTAINER_ID" /usr/local/bin/claude --dangerously-skip-permissions "$@"
"""

            wrapper_script.write_text(wrapper_content)
            wrapper_script.chmod(0o755)

            # No symlinks needed - wrapper script uses absolute paths

            # Use ONLY the wrapper directory in PATH - no host PATH at all
            isolated_path = str(wrapper_dir)
            yield isolated_path

        finally:
            # Clean up wrapper script
            if wrapper_script.exists():
                wrapper_script.unlink()

    def get_subprocess_env(self, container_id: str, wrapper_path: str) -> dict:
        """Get environment variables for subprocess calls.

        Args:
            container_id: Container ID to set for Claude wrapper
            wrapper_path: Modified PATH with wrapper directory

        Returns:
            Environment dict with modified PATH and CLAUDE_CONTAINER_ID
        """
        env = os.environ.copy()
        env["PATH"] = wrapper_path
        env["CLAUDE_CONTAINER_ID"] = container_id
        return env

    @contextmanager
    def wrapper_and_container(
        self,
        working_dir: Path,
        wrapper_script_path: Path,
        docker_image: str,
        container_name: str,
    ):
        """Set up wrapper and container with automatic cleanup.

        Args:
            working_dir: Working directory to mount
            wrapper_script_path: Path to the wrapper script
            docker_image: Docker image to use
            container_name: Unique container identifier

        Yields:
            tuple: (wrapper_path, container_id)
        """
        with (
            self.wrapper(working_dir, wrapper_script_path) as wrapper_path,
            self.container(docker_image, container_name, working_dir) as container_id,
        ):
            yield wrapper_path, container_id

    @property
    def docker_path(self) -> str:
        """Get the path to the real Docker binary."""
        return self._docker_path

    @property
    def is_setup(self) -> bool:
        """Check if wrapper is currently set up."""
        return self._wrapper_setup

    @contextmanager
    def container(self, image: str, task_id: str, working_dir: Path):
        """Context manager for a long-running container.

        Args:
            image: Docker image name (e.g., 'claude-dev:task-123')
            task_id: Task identifier
            working_dir: Working directory to mount

        Yields:
            str: Container ID for use with setup scripts and docker exec
        """
        container = None
        self._current_container = None  # Track current container for cleanup
        try:
            # Use shared git volume (created once, reused across all tasks)
            git_volume_name = "claude_shared_git"

            # Ensure the shared git volume exists
            try:
                self._docker_client.volumes.get(git_volume_name)
            except docker.errors.NotFound:
                self._docker_client.volumes.create(name=git_volume_name)

            # Build volumes dict
            volumes = {
                str(working_dir): {"bind": "/workspace", "mode": "rw"},
                git_volume_name: {"bind": "/git", "mode": "rw"},  # RW during setup
            }

            # Start long-running container using Docker SDK
            container = self._docker_client.containers.run(
                image,
                command=["sleep", "infinity"],
                volumes=volumes,
                working_dir="/workspace",
                detach=True,
            )

            container_id = container.id
            self._current_container = container  # Track for cleanup

            yield container_id

        except docker.errors.DockerException as e:
            raise RuntimeError(f"Failed to start container: {e}")
        finally:

            # Clean up container (use tracked container in case of remounting)
            cleanup_container = self._current_container or container
            if cleanup_container:
                # Log but don't fail - container might already be gone
                with suppress(docker.errors.DockerException):
                    cleanup_container.remove(force=True)

    def remount_git_readonly(
        self, container_id: str, image: str, working_dir: Path,
    ) -> str:
        """Recreate container with /git mounted read-only for security after pre-task setup.

        Args:
            container_id: Current container ID to replace
            image: Docker image to use for new container
            working_dir: Working directory to mount

        Returns:
            str: New container ID with read-only /git mount
        """
        # Stop and remove the current container
        old_container = self._docker_client.containers.get(container_id)
        old_container.remove(force=True)

        # Create new container with read-only /git volume
        git_volume_name = "claude_shared_git"
        volumes = {
            str(working_dir): {"bind": "/workspace", "mode": "rw"},
            git_volume_name: {"bind": "/git", "mode": "ro"},  # Now read-only
        }

        # Start new container
        new_container = self._docker_client.containers.run(
            image,
            command=["sleep", "infinity"],
            volumes=volumes,
            working_dir="/workspace",
            detach=True,
        )

        # Update current container tracking
        self._current_container = new_container  # Update tracked container
        return new_container.id

    def run_pre_task_setup(
        self,
        container_id: str,
        task_id: str,
        working_dir: Path,
        config,
        wrapper_path: str,
    ) -> None:
        """Run pre-task setup script if configured.

        Args:
            config: OptimizerConfig instance containing setup script path
            wrapper_path: Modified PATH with wrapper directory
        """
        if not config.pre_task_setup_script:
            return

        setup_script_path = Path(config.pre_task_setup_script)
        if not setup_script_path.exists():
            raise RuntimeError(f"Pre-task setup script not found: {setup_script_path}")

        try:
            subprocess.run(
                [
                    str(setup_script_path),
                    container_id,
                    task_id,
                    str(working_dir),
                ],
                check=True,
                env=self.get_subprocess_env(container_id, wrapper_path),
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError("Pre-task setup script failed") from e

