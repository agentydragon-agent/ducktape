"""Docker management for Claude Code execution in isolated containers."""

import shutil
import os
from pathlib import Path
from typing import Optional


class DockerManager:
    """Manages Docker wrapper setup for Claude Code execution."""
    
    def __init__(self):
        """Initialize DockerManager and locate Docker binary."""
        self._original_path = os.environ.get("PATH", "")
        self._docker_path = self._find_docker()
        self._wrapper_setup = False
        
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
                "Docker is required to run Claude Code agents in isolated containers. "
                "Install Docker and ensure it is in your PATH."
            )
        return docker_path
    
    def setup_wrapper(self, base_dir: Path, wrapper_script_path: Path) -> Path:
        """Set up Docker wrapper script for Claude Code isolation.
        
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