"""Docker management for coding agent execution in isolated containers."""

import shutil
import os
import subprocess
from pathlib import Path
from typing import Optional
from contextlib import contextmanager
import docker


class DockerManager:
    """Manages Docker wrapper setup for coding agent execution."""
    
    def __init__(self):
        """Initialize DockerManager and locate Docker binary."""
        self._original_path = os.environ.get("PATH", "")
        self._docker_path = self._find_docker()
        self._wrapper_setup = False
        self._docker_client = docker.from_env()
        
    def _find_docker(self) -> str:
        """Find the real Docker binary.
        
        Returns:
            Path to the Docker executable
            
        Raises:
            RuntimeError: If Docker is not found
        """
        docker_path = shutil.which("docker", path=self._original_path)
        if docker_path is None:
            raise RuntimeError(
                "Docker is required to run coding agents in isolated containers. "
                "Install Docker and ensure it is in your PATH."
            )
        return docker_path
    
    def setup_wrapper(self, base_dir: Path, wrapper_script_path: Path) -> Path:
        """Set up Docker wrapper script for coding agent isolation.
        
        Args:
            base_dir: Base directory for the run
            wrapper_script_path: Path to the docker_claude_wrapper.sh script
            
        Returns:
            Path to the installed wrapper script
        """
        wrapper_dir = base_dir / "bin"
        wrapper_dir.mkdir(parents=True, exist_ok=True)
        wrapper_script = wrapper_dir / "claude"
        
        # Copy the external Docker wrapper script
        if not wrapper_script_path.exists():
            raise FileNotFoundError(f"Docker wrapper script not found: {wrapper_script_path}")
            
        shutil.copy2(wrapper_script_path, wrapper_script)
        wrapper_script.chmod(0o755)
        
        # Prepend wrapper directory to PATH
        os.environ["PATH"] = f"{wrapper_dir}:{self._original_path}"
        self._wrapper_setup = True
        
        return wrapper_script
        
    def cleanup(self) -> None:
        """Restore original PATH."""
        if self._wrapper_setup:
            os.environ["PATH"] = self._original_path
            self._wrapper_setup = False
            
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
        try:
            # Build volumes dict
            volumes = {str(working_dir): {"bind": "/workspace", "mode": "rw"}}
            
            # Start long-running container using Docker SDK
            container = self._docker_client.containers.run(
                image,
                command=["sleep", "infinity"],
                volumes=volumes,
                working_dir="/workspace",
                detach=True
            )
            
            container_id = container.id
            
            # Set environment variable for wrapper script
            os.environ["CLAUDE_CONTAINER_ID"] = container_id
            
            yield container_id
            
        except docker.errors.DockerException as e:
            raise RuntimeError(f"Failed to start container: {e}")
        finally:
            # Clean up environment variable
            if "CLAUDE_CONTAINER_ID" in os.environ:
                del os.environ["CLAUDE_CONTAINER_ID"]
                
            # Clean up container
            if container:
                try:
                    container.remove(force=True)
                except docker.errors.DockerException:
                    # Log but don't fail - container might already be gone
                    pass
    
    def run_pre_task_setup(self, container_id: str, task_id: str, working_dir: Path, config) -> None:
        """Run pre-task setup script if configured.
        
        Args:
            container_id: Container ID to configure
            task_id: Task identifier
            working_dir: Working directory path
            config: OptimizerConfig instance containing setup script path
        """
        if not config.pre_task_setup_script:
            return
            
        setup_script_path = Path(config.pre_task_setup_script)
        if not setup_script_path.exists():
            raise RuntimeError(f"Pre-task setup script not found: {setup_script_path}")
            
        try:
            subprocess.run([
                str(setup_script_path),
                container_id,
                task_id,
                str(working_dir)
            ], check=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Pre-task setup script failed: {e}")