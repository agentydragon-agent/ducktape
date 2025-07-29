"""Safe containerized Claude interface with ClaudeSDKClient compatibility."""

import asyncio
import fnmatch
import json
import os
import shutil
import tempfile
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import AsyncIterator, Dict, Any, List, Optional

import docker
from claude_code_sdk import (
    ClaudeCodeOptions,
    ClaudeSDKClient,
    SystemMessage,
    UserMessage, 
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
)


class FileCollection:
    """Ergonomic interface for working with collected files."""
    
    def __init__(self, base_dir: Path):
        self._base_dir = base_dir
        
    def list_files(self) -> List[Path]:
        """List all collected files."""
        return [f for f in self._base_dir.rglob("*") if f.is_file()]
        
    def read_file(self, relative_path: str) -> str:
        """Read a specific file's content."""
        return (self._base_dir / relative_path).read_text()
        
    def to_grader_format(self) -> List[Dict[str, str]]:
        """Convert to format expected by grader (matches gather_agent_files output)."""
        files_info = []
        for file_path in self.list_files():
            relative = file_path.relative_to(self._base_dir).as_posix()
            content = file_path.read_text()
            files_info.append({"path": relative, "content": content})
        return files_info


class TaskClaude:
    """Containerized Claude client with ClaudeSDKClient-compatible interface.
    
    Provides the same API as ClaudeSDKClient but runs Claude inside Docker containers
    with proper PATH isolation and automatic file collection.
    """
    
    def __init__(self, task_id: str, config, output_dir: Path):
        self.task_id = task_id
        self.config = config
        self._output_dir = output_dir
        self._docker_client = docker.from_env()
        self._container = None
        self._wrapper_dir = None
        self._original_path = None
        self._path_isolated = False
        self._message_queue = asyncio.Queue()
        self._query_task = None
        self._logger = None
        
    @property
    def container_id(self) -> str:
        """Get container ID for external operations."""
        if not self._container:
            raise RuntimeError("Container not started")
        return self._container.id
        
    def _ensure_path_isolated(self):
        """Runtime safety check - call before any subprocess operations."""
        if not self._path_isolated:
            raise RuntimeError(
                "PATH isolation not active - TaskClaude must be used as context manager"
            )
            
    def _isolate_path(self):
        """Apply PATH isolation - makes host claude unreachable."""
        if not self._wrapper_dir:
            raise RuntimeError("Wrapper not setup before PATH isolation")
        
        self._original_path = os.environ.get("PATH", "")
        os.environ["PATH"] = str(self._wrapper_dir)  # ONLY wrapper directory
        self._path_isolated = True
        
    def _restore_path(self):
        """Restore original PATH - critical for cleanup."""
        if self._original_path is not None:
            os.environ["PATH"] = self._original_path
            self._path_isolated = False
            
    def _get_isolated_env(self) -> Dict[str, str]:
        """Get environment with PATH isolation for subprocess calls."""
        env = os.environ.copy()
        if self._wrapper_dir:
            env["PATH"] = str(self._wrapper_dir)
        return env
        
    async def query(self, task: str) -> None:
        """Start Claude query - matches ClaudeSDKClient.query() signature."""
        self._ensure_path_isolated()
        
        # Create ClaudeCodeOptions pointing to container workspace
        options = ClaudeCodeOptions(
            allowed_tools=None,  # Full tool access for autonomous execution
            cwd=Path("/workspace"),  # Container workspace path
            max_turns=self.config.rollouts.max_turns,
            permission_mode="bypassPermissions",  # Required for Docker container execution
            mcp_servers={},
        )
        
        # Store options for receive_messages
        self._claude_options = options
        self._task = task
        
    async def receive_messages(self) -> AsyncIterator[Any]:
        """Receive messages from Claude - matches ClaudeSDKClient.receive_messages()."""
        self._ensure_path_isolated()
        
        # Use the actual ClaudeSDKClient but with PATH isolation active
        async with ClaudeSDKClient(options=self._claude_options) as client:
            await client.query(self._task)
            async for message in client.receive_messages():
                yield message
    
    async def setup_system_prompt(self, system_prompt: str):
        """Write CLAUDE.md inside the container."""
        self._ensure_path_isolated()
        
        # Write CLAUDE.md inside the container
        write_cmd = [
            "docker", "exec", "-i", self._container.id,
            "sh", "-c", "cat > /workspace/CLAUDE.md"
        ]
        
        process = await asyncio.create_subprocess_exec(
            *write_cmd,
            stdin=asyncio.subprocess.PIPE,
            env=self._get_isolated_env()
        )
        await process.communicate(input=system_prompt.encode('utf-8'))
        
        # Set environment variables inside container
        bash_timeout = str(self.config.rollouts.bash_timeout_ms)
        env_cmd = [
            "docker", "exec", self._container.id,
            "sh", "-c", f"echo 'export BASH_MAX_TIMEOUT_MS={bash_timeout}' >> /workspace/.bashrc"
        ]
        
        await asyncio.create_subprocess_exec(*env_cmd, env=self._get_isolated_env())
        
    async def collect_outputs(self) -> FileCollection:
        """Copy files from container to host with filtering applied."""
        self._ensure_path_isolated()
        
        if not self._container:
            raise RuntimeError("No container to collect from")
            
        # Copy files from container to host with exclusion patterns
        await self._copy_files_from_container()
        
        return FileCollection(self._output_dir)
        
    async def _copy_files_from_container(self) -> None:
        """Copy files from container to host directory for grader access."""
        try:
            # List all files in the container workspace
            list_cmd = [
                "docker", "exec", self._container.id,
                "find", "/workspace", "-type", "f"
            ]
            
            result = await asyncio.create_subprocess_exec(
                *list_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await result.communicate()
            
            if result.returncode != 0:
                error_msg = stderr.decode()
                self._logger.error("Failed to list container files", error=error_msg)
                raise RuntimeError(f"Failed to list container files: {error_msg}")
                
            # Process each file found in container
            container_files = stdout.decode().strip().split('\n')
            copied_count = 0
            excluded_count = 0
            
            for container_file_path in container_files:
                if not container_file_path.strip():
                    continue
                    
                # Calculate relative path from container workdir
                if not container_file_path.startswith("/workspace"):
                    continue
                    
                # Remove the container workdir prefix to get relative path
                relative_path = container_file_path[len("/workspace"):].lstrip('/')
                filename = Path(container_file_path).name
                
                # Apply same exclusion logic as gather_agent_files
                if self._should_exclude_file(relative_path, filename):
                    excluded_count += 1
                    continue
                    
                # Create host destination path
                host_file_path = self._output_dir / relative_path
                host_file_path.parent.mkdir(parents=True, exist_ok=True)
                
                # Copy file from container to host
                copy_cmd = [
                    "docker", "cp", 
                    f"{self._container.id}:{container_file_path}",
                    str(host_file_path)
                ]
                
                copy_result = await asyncio.create_subprocess_exec(
                    *copy_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                await copy_result.wait()
                
                if copy_result.returncode == 0:
                    copied_count += 1
                else:
                    copy_stderr = await copy_result.stderr.read() if copy_result.stderr else b""
                    error_msg = copy_stderr.decode()
                    self._logger.error("Failed to copy file", 
                                    container_path=container_file_path,
                                    host_path=str(host_file_path),
                                    error=error_msg)
                    raise RuntimeError(f"Failed to copy file {container_file_path}: {error_msg}")
                    
            self._logger.info("Container files copied", 
                            copied_files=copied_count,
                            excluded_files=excluded_count)
            
        except Exception as e:
            self._logger.error("FATAL: Error copying files from container", error=str(e))
            # This is not recoverable - grader needs these files
            raise RuntimeError(f"FATAL: Failed to copy files from container: {e}")
            
    def _should_exclude_file(self, relative_path: str, filename: str) -> bool:
        """Check if a file should be excluded based on configuration patterns."""
        return any(fnmatch.fnmatch(relative_path, pattern) or fnmatch.fnmatch(filename, pattern) 
                   for pattern in self.config.exclude_patterns)
            
    def _get_task_from_db(self):
        """Get task from database."""
        from database import get_db_session, SeedTask
        
        with get_db_session() as session:
            task = session.query(SeedTask).filter(SeedTask.task_id == self.task_id).first()
            if not task:
                raise ValueError(f"Task '{self.task_id}' not found in database")
            return task
            
    def _setup_wrapper(self, container_id: str) -> None:
        """Set up Claude wrapper script with container ID."""
        wrapper_dir = self._output_dir / "bin"
        wrapper_dir.mkdir(parents=True, exist_ok=True)
        
        wrapper_script = wrapper_dir / "claude"
        
        # Find docker binary path
        docker_path = shutil.which("docker")
        if not docker_path:
            raise RuntimeError("Docker binary not found in PATH")
        
        # Generate wrapper script inline with container ID
        wrapper_content = f"""#!/bin/sh
# Docker wrapper for Claude CLI
exec {docker_path} exec -i {container_id} /usr/local/bin/claude --dangerously-skip-permissions "$@"
"""
        
        wrapper_script.write_text(wrapper_content)
        wrapper_script.chmod(0o755)
        
        self._wrapper_dir = wrapper_dir
        
    async def _start_container(self):
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
            str(self._output_dir): {"bind": "/workspace", "mode": "rw"},
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
        if self.config.pre_task_setup_script:
            await self._run_pre_task_setup(task_db)
            
        # ALWAYS remount git as read-only for security
        await self._remount_git_readonly(docker_image)
    
    async def _run_pre_task_setup(self, task_db):
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
            str(self._output_dir)
        )
        
        if await process.wait() != 0:
            raise RuntimeError("Pre-task setup script failed")
    
    async def _remount_git_readonly(self, docker_image: str):
        """Remount git volume as read-only for security."""
        # Stop current container
        old_container_id = self._container.id
        self._container.remove(force=True)
        
        # Start new container with RO git mount
        git_volume_name = "claude_shared_git"
        volumes = {
            str(self._output_dir): {"bind": "/workspace", "mode": "rw"},
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
    
    async def __aenter__(self) -> "TaskClaude":
        """Context manager entry - setup container and PATH isolation."""
        # Set up logger
        from logging_utils import DualOutputLogging
        self._logger = DualOutputLogging.get_logger().bind(task_id=self.task_id)
        
        # Start container first, then setup wrapper with container ID
        await self._start_container()
        self._setup_wrapper(self._container.id)
        
        # Apply PATH isolation - CRITICAL SECTION
        self._isolate_path()
        
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - restore PATH and cleanup container."""
        # Restore PATH FIRST - critical for cleanup
        self._restore_path()
        
        # Stop query task if running
        if self._query_task and not self._query_task.done():
            self._query_task.cancel()
            
        # Cleanup container and wrapper
        await self._cleanup()


@asynccontextmanager
async def task_claude(task_id: str, config, output_dir: Path) -> AsyncIterator[TaskClaude]:
    """Context manager for Claude task execution.
    
    Args:
        task_id: Task identifier from database
        config: OptimizerConfig instance
        output_dir: Directory for output files
        
    Yields:
        TaskClaude: Containerized Claude interface with ClaudeSDKClient compatibility
    """
    claude = TaskClaude(task_id, config, output_dir)
    
    async with claude as client:
        yield client