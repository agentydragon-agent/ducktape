"""Safe containerized Claude interface with ClaudeSDKClient compatibility."""

import asyncio
import fnmatch
import io
import json
import os
import shutil
import tarfile
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


from dataclasses import dataclass

@dataclass  
class ContainerizedClaudeCodeOptions(ClaudeCodeOptions):
    """ClaudeCodeOptions with containerization support."""
    claude_binary: str | None = None


def _monkey_patch_claude_sdk_for_containerization():
    """Monkeypatch Claude SDK to use our containerized wrapper instead of PATH lookup."""
    import claude_code_sdk
    
    # Replace the options class so we can pass claude_binary
    claude_code_sdk.types.ClaudeCodeOptions = ContainerizedClaudeCodeOptions
    claude_code_sdk.ClaudeCodeOptions = ContainerizedClaudeCodeOptions
    
    # Override _find_cli to use claude_binary from options
    from claude_code_sdk._internal.transport.subprocess_cli import SubprocessCLITransport
    
    def _patched_find_cli(self) -> str:
        """Use claude_binary from options if provided, otherwise use PATH."""
        claude_binary = getattr(self._options, 'claude_binary', None)
        if claude_binary:
            return claude_binary
        
        # This should never happen in containerized mode
        raise RuntimeError("No claude_binary specified in options")
    
    SubprocessCLITransport._find_cli = _patched_find_cli


# Apply monkeypatch once at module level  
_monkey_patch_claude_sdk_for_containerization()


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
        self._wrapper_script_path = None
        self._message_queue = asyncio.Queue()
        self._query_task = None
        self._logger = None
        
        # Find docker path for wrapper creation
        self._docker_path = shutil.which("docker")
        if not self._docker_path:
            raise RuntimeError("Docker binary not found in PATH")
        
    @property
    def container_id(self) -> str:
        """Get container ID for external operations."""
        if not self._container:
            raise RuntimeError("Container not started")
        return self._container.id
        
    def _ensure_container_ready(self):
        """Runtime safety check - call before any container operations."""
        if not self._container:
            raise RuntimeError("Container not started - TaskClaude must be used as context manager")
            
    async def query(self, task: str) -> None:
        """Start Claude query - matches ClaudeSDKClient.query() signature."""
        self._ensure_container_ready()
        
        # Create ClaudeCodeOptions with containerization settings
        options = ContainerizedClaudeCodeOptions(
            allowed_tools=None,  # Full tool access for autonomous execution
            cwd=".",  # Use current directory for SDK check - container wrapper handles actual cwd
            max_turns=self.config.rollouts.max_turns,
            permission_mode="bypassPermissions",  # Required for Docker container execution  
            mcp_servers={},
            claude_binary=str(self._wrapper_script_path),  # Use our containerized wrapper
        )
        
        # Store options for receive_messages
        self._claude_options = options
        self._task = task
        
    async def receive_messages(self) -> AsyncIterator[Any]:
        """Receive messages from Claude - matches ClaudeSDKClient.receive_messages()."""
        self._ensure_container_ready()
        
        # Use the actual ClaudeSDKClient but with PATH isolation active
        async with ClaudeSDKClient(options=self._claude_options) as client:
            await client.query(self._task)
            async for message in client.receive_messages():
                yield message
    
    def setup_system_prompt(self, system_prompt: str):
        """Write CLAUDE.md inside the container (call before PATH isolation)."""
        if not self._container:
            raise RuntimeError("Container must be started before setting up system prompt")
        
        self._logger.debug("Writing system prompt to container", 
                         container_id=self._container.id,
                         prompt_length=len(system_prompt))
        
        # Write CLAUDE.md using Docker SDK
        self._container.put_archive('/workspace', 
            self._create_tar_archive('CLAUDE.md', system_prompt))
        
    async def collect_outputs(self) -> FileCollection:
        """Copy files from container to host with filtering applied."""
        self._ensure_container_ready()
        
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
            
    def _create_tar_archive(self, filename: str, content: str) -> bytes:
        """Create a tar archive containing a single file."""
        tar_buffer = io.BytesIO()
        
        with tarfile.open(fileobj=tar_buffer, mode='w') as tar:
            # Create tarinfo for the file
            tarinfo = tarfile.TarInfo(name=filename)
            tarinfo.size = len(content.encode('utf-8'))
            tarinfo.mode = 0o644
            
            # Add file to archive
            tar.addfile(tarinfo, io.BytesIO(content.encode('utf-8')))
        
        tar_buffer.seek(0)
        return tar_buffer.read()
            
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
        
        # Use pre-found docker path (found before PATH isolation)
        docker_path = self._docker_path
        
        # Generate wrapper script inline with container ID and environment
        bash_timeout = str(self.config.rollouts.bash_timeout_ms)
        wrapper_content = f"""#!/bin/sh
# Docker wrapper for Claude CLI with environment variables and working directory
exec {docker_path} exec -i -w /workspace -e BASH_MAX_TIMEOUT_MS={bash_timeout} {container_id} /usr/local/bin/claude "$@"
"""
        
        wrapper_script.write_text(wrapper_content)
        wrapper_script.chmod(0o755)
        
        self._logger.debug("Claude wrapper created", 
                         wrapper_path=str(wrapper_script),
                         docker_path=docker_path,
                         container_id=container_id)
        
        # Store the wrapper script path for ClaudeCodeOptions
        self._wrapper_script_path = str(wrapper_script)
        
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
            
        if self._wrapper_script_path and Path(self._wrapper_script_path).exists():
            try:
                # Remove the wrapper script and its parent directory
                wrapper_path = Path(self._wrapper_script_path)
                shutil.rmtree(wrapper_path.parent)
            except:
                pass  # Ignore cleanup errors
            self._wrapper_script_path = None
    
    async def __aenter__(self) -> "TaskClaude":
        """Context manager entry - setup container and wrapper."""
        # Set up logger
        from logging_utils import DualOutputLogging
        self._logger = DualOutputLogging.get_logger().bind(task_id=self.task_id)
        
        # Start container first, then setup wrapper with container ID
        await self._start_container()
        # Note: _start_container includes remounting, so container.id is final after it returns
        self._setup_wrapper(self._container.id)
        
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - cleanup container and wrapper."""
        # Stop query task if running
        if self._query_task and not self._query_task.done():
            self._query_task.cancel()
            
        # Cleanup container and wrapper
        await self._cleanup()


class _TaskClaudeProxy:
    """Proxy to handle system prompt setup after container initialization."""
    
    def __init__(self, claude: TaskClaude):
        self._claude = claude
        self._setup_done = False
        
    async def setup_system_prompt(self, system_prompt: str):
        """Setup system prompt after container and wrapper initialization."""
        # Start container and setup wrapper first
        from logging_utils import DualOutputLogging
        self._claude._logger = DualOutputLogging.get_logger().bind(task_id=self._claude.task_id)
        
        await self._claude._start_container()
        # Note: _start_container includes remounting, so container.id is final after it returns
        self._claude._setup_wrapper(self._claude._container.id)
        
        # Now write system prompt to container
        self._claude.setup_system_prompt(system_prompt)
        self._setup_done = True
        
    async def query(self, task: str) -> None:
        """Delegate to actual TaskClaude."""
        if not self._setup_done:
            raise RuntimeError("Must call setup_system_prompt first")
        return await self._claude.query(task)
        
    async def receive_messages(self) -> AsyncIterator[Any]:
        """Delegate to actual TaskClaude.""" 
        if not self._setup_done:
            raise RuntimeError("Must call setup_system_prompt first")
        async for message in self._claude.receive_messages():
            yield message
            
    async def collect_outputs(self) -> FileCollection:
        """Delegate to actual TaskClaude."""
        return await self._claude.collect_outputs()
        
    @property
    def container_id(self) -> str:
        """Delegate to actual TaskClaude."""
        return self._claude.container_id


@asynccontextmanager  
async def task_claude(task_id: str, config, output_dir: Path) -> AsyncIterator[_TaskClaudeProxy]:
    """Context manager for Claude task execution.
    
    Args:
        task_id: Task identifier from database
        config: OptimizerConfig instance
        output_dir: Directory for output files
        
    Yields:
        _TaskClaudeProxy: Proxy that handles system prompt setup before PATH isolation
    """
    claude = TaskClaude(task_id, config, output_dir)
    proxy = _TaskClaudeProxy(claude)
    
    try:
        yield proxy
    finally:
        # Cleanup via the actual TaskClaude instance
        if proxy._setup_done:
            await claude._cleanup()