"""Simple async interface for running Claude in task-specific Docker containers."""

import asyncio
import subprocess
from pathlib import Path
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, Any
import docker
import shutil
import os
import tempfile


class TaskClaude:
    """Async Claude interface with automatic Docker container management."""
    
    def __init__(self, task_id: str, config):
        self.task_id = task_id
        self.config = config
        self._docker_client = docker.from_env()
        self._container = None
        self._wrapper_dir = None
        
    async def query(self, prompt: str) -> AsyncIterator[str]:
        """Query Claude with automatic streaming response."""
        # Build command for Claude in container
        cmd = [
            "docker", "exec", "-i", self._container.id,
            "claude", "--stream", prompt
        ]
        
        # Run Claude and stream responses
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._get_env()
        )
        
        async for line in process.stdout:
            if line:
                yield line.decode('utf-8').rstrip()
                
        await process.wait()
        if process.returncode != 0:
            stderr = await process.stderr.read()
            raise RuntimeError(f"Claude query failed: {stderr.decode()}")
    
    def _get_task_from_db(self):
        """Get task from database."""
        from database import get_db_session, SeedTask
        
        with get_db_session() as session:
            task = session.query(SeedTask).filter(SeedTask.task_id == self.task_id).first()
            if not task:
                raise ValueError(f"Task '{self.task_id}' not found in database")
            return task
    
    def _setup_wrapper(self, working_dir: Path) -> Path:
        """Set up Claude wrapper script."""
        wrapper_dir = working_dir / "bin"
        wrapper_dir.mkdir(parents=True, exist_ok=True)
        
        wrapper_script = wrapper_dir / "claude" 
        external_wrapper = Path(__file__).parent / "docker_claude_wrapper.sh"
        
        if not external_wrapper.exists():
            raise FileNotFoundError(f"Docker wrapper not found: {external_wrapper}")
            
        shutil.copy2(external_wrapper, wrapper_script)
        wrapper_script.chmod(0o755)
        
        self._wrapper_dir = wrapper_dir
        return wrapper_dir
        
    def _get_env(self) -> Dict[str, str]:
        """Get environment for subprocess calls."""
        env = os.environ.copy()
        if self._wrapper_dir:
            env["PATH"] = f"{self._wrapper_dir}:{env.get('PATH', '')}"
        if self._container:
            env["CLAUDE_CONTAINER_ID"] = self._container.id
        return env
        
    async def _start_container(self, working_dir: Path):
        """Start Docker container for the task."""
        task_db = self._get_task_from_db()
        docker_image = task_db.docker_image_tag
        
        # Ensure shared git volume exists
        git_volume_name = "claude_shared_git"
        try:
            self._docker_client.volumes.get(git_volume_name)
        except docker.errors.NotFound:
            self._docker_client.volumes.create(name=git_volume_name)
        
        # Start container
        volumes = {
            str(working_dir): {"bind": "/workspace", "mode": "rw"},
            git_volume_name: {"bind": "/git", "mode": "rw"}
        }
        
        self._container = self._docker_client.containers.run(
            docker_image,
            command=["sleep", "infinity"],
            volumes=volumes,
            working_dir="/workspace",
            detach=True
        )
        
        # Run pre-task setup if configured
        if task_db.pre_task_setup_script and self.config.pre_task_setup_script:
            await self._run_pre_task_setup(task_db, working_dir)
            await self._remount_git_readonly(docker_image, working_dir)
    
    async def _run_pre_task_setup(self, task_db, working_dir: Path):
        """Run pre-task setup script."""
        if not self.config.pre_task_setup_script:
            return
            
        setup_script = Path(self.config.pre_task_setup_script)
        if not setup_script.exists():
            raise FileNotFoundError(f"Pre-task setup script not found: {setup_script}")
            
        process = await asyncio.create_subprocess_exec(
            str(setup_script),
            self._container.id,
            self.task_id,
            str(working_dir),
            env=self._get_env()
        )
        
        if await process.wait() != 0:
            raise RuntimeError("Pre-task setup script failed")
    
    async def _remount_git_readonly(self, docker_image: str, working_dir: Path):
        """Remount git volume as read-only for security."""
        # Stop current container
        old_container_id = self._container.id
        self._container.remove(force=True)
        
        # Start new container with RO git mount
        git_volume_name = "claude_shared_git"
        volumes = {
            str(working_dir): {"bind": "/workspace", "mode": "rw"},
            git_volume_name: {"bind": "/git", "mode": "ro"}  # Now read-only
        }
        
        self._container = self._docker_client.containers.run(
            docker_image,
            command=["sleep", "infinity"],
            volumes=volumes,
            working_dir="/workspace",
            detach=True
        )
    
    async def _cleanup(self):
        """Clean up container and wrapper."""
        if self._container:
            try:
                self._container.remove(force=True)
            except:
                pass  # Ignore cleanup errors
            self._container = None
            
        if self._wrapper_dir and self._wrapper_dir.exists():
            try:
                shutil.rmtree(self._wrapper_dir)
            except:
                pass  # Ignore cleanup errors
            self._wrapper_dir = None


@asynccontextmanager
async def task_claude(task_id: str, config, working_dir: Path = None) -> AsyncIterator[TaskClaude]:
    """Context manager for Claude task execution.
    
    Args:
        task_id: Task identifier from database
        config: OptimizerConfig instance
        working_dir: Working directory (defaults to temp dir)
        
    Yields:
        TaskClaude: Async Claude interface
    """
    if working_dir is None:
        working_dir = Path(tempfile.mkdtemp(prefix=f"claude_task_{task_id}_"))
        cleanup_working_dir = True
    else:
        cleanup_working_dir = False
        
    claude = TaskClaude(task_id, config)
    
    try:
        # Setup wrapper and container
        claude._setup_wrapper(working_dir)
        await claude._start_container(working_dir)
        
        yield claude
        
    finally:
        # Cleanup
        await claude._cleanup()
        
        if cleanup_working_dir:
            try:
                shutil.rmtree(working_dir)
            except:
                pass  # Ignore cleanup errors