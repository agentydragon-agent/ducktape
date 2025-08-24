"""Mini Codex runner implementation with Docker containerization."""

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import docker
import docker.errors

from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError
from openai.types.responses import Response, ResponseOutputMessage, ResponseFunctionToolCall, ResponseOutputText

from claude_optimizer.core.file_utils import collect_workspace_files
from claude_optimizer.core.jsonl_logger import JSONLLogger
from claude_optimizer.core.logging_openai_client import LoggingOpenAIClient
from claude_optimizer.core.logging_utils import DualOutputLogging
from claude_optimizer.core.models import (
    AssistantMessage,
    TaskSetup,
    DockerConfig,
    GitCloneConfig,
    FinalOutput,
    Rollout,
    RunnerEnvironment,
    TaskDefinition,
    ToolCall,
    ToolResult,
    TrajectoryItem,
    UserInput,
)
from claude_optimizer.core.runners.base import AgentRunner


class MiniCodexRunner(AgentRunner):
    """Runner for mini_codex agent with integrated execution logic."""
    
    # Configuration defaults
    DEFAULT_TIMEOUT_S = 30
    TRUNCATE_BYTES = 8192
    API_MAX_RETRIES = 2
    
    # Class-level rate limiter shared across all instances
    # Default to 5 concurrent API calls to avoid overwhelming OpenAI
    _api_semaphore = None  # Will be initialized with config value
    
    def __init__(self, runner_id: str, config: dict):
        """Initialize mini_codex runner.
        
        Args:
            runner_id: Unique identifier for this runner instance
            config: Mini codex configuration including:
                - model: OpenAI model to use (default: o4-mini)
                - reasoning_effort: Reasoning effort level (minimal/medium/high, default: medium)
                - timeout_s: Timeout for commands in seconds
                - truncate_bytes: Max bytes for output truncation
                - max_cycles: Maximum tool use cycles per turn
                - openai_client: Optional LoggingOpenAIClient for API logging
                - openai_log_path: Path for OpenAI API logs if client not provided
        """
        super().__init__(runner_id, config)
        self.model = config.get("model", "o4-mini")
        self.reasoning_effort = config.get("reasoning_effort", "medium")
        self.timeout_s = config.get("timeout_s", self.DEFAULT_TIMEOUT_S)
        self.truncate_bytes = config.get("truncate_bytes", self.TRUNCATE_BYTES)
        self.max_cycles = config.get("max_cycles", 8)
        # System instructions will be set per task by the optimizer
        self.system_instructions = None
        self.api_max_retries = config.get("api_max_retries", self.API_MAX_RETRIES)
        
        # Initialize class-level semaphore if not already done
        if MiniCodexRunner._api_semaphore is None:
            max_concurrent_api_calls = config.get("max_concurrent_api_calls", 5)
            MiniCodexRunner._api_semaphore = asyncio.Semaphore(max_concurrent_api_calls)
        
        # Working directory for the agent (may be subdir of workspace)
        self.agent_cwd = None
        
        # Docker configuration - will be set from task setup during setup()
        # TODO: Consider supporting (task, runner) specific Docker configs in the future
        self.docker_config = None
        self.container = None
        self.docker_client = None
        
        # Set up OpenAI client - always use AsyncOpenAI
        from openai import AsyncOpenAI
        # Ignore any passed client and always create AsyncOpenAI for async support
        self.openai_client = AsyncOpenAI()
        
        # Always create a JSONL logger
        log_path = config.get("openai_log_path", Path.cwd() / "minicodex_openai.jsonl")
        self.jsonl_logger = JSONLLogger(log_path)
    
    def _truncate(self, s: str, limit: int) -> str:
        """Truncate string to limit with indicator."""
        if len(s) <= limit:
            return s
        return s[: limit - 12] + "\n[TRUNCATED]"
    
    async def _run_command(self, cmd: List[str], timeout_s: int, cwd: Optional[str] = None) -> Tuple[int, str, str]:
        """Run command with timeout, either in Docker container or locally.
        
        Returns: (exit_code, stdout, stderr)
        """
        if self.docker_config and self.container:
            # Run in Docker container
            return await self._run_command_docker(cmd, timeout_s, cwd)
        else:
            # Run locally (when docker=null or container not started)
            return await self._run_command_local(cmd, timeout_s, cwd)
    
    async def _run_command_local(self, cmd: List[str], timeout_s: int, cwd: Optional[str] = None) -> Tuple[int, str, str]:
        """Run command locally with timeout using async subprocess.
        
        Returns: (exit_code, stdout, stderr)
        """
        # Use provided cwd, or agent's working directory
        if cwd is None:
            cwd = self.agent_cwd or str(self.workspace_path)
        
        try:
            # Use asyncio.create_subprocess_exec for non-blocking execution
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout_s
                )
                exit_code = proc.returncode
                stdout = stdout_bytes.decode('utf-8') if stdout_bytes else ""
                stderr = stderr_bytes.decode('utf-8') if stderr_bytes else ""
                
                return (exit_code, self._truncate(stdout, self.truncate_bytes), 
                       self._truncate(stderr, self.truncate_bytes))
            except asyncio.TimeoutError:
                # Kill the process and return timeout error
                proc.kill()
                await proc.wait()
                return (
                    124,
                    "",
                    self._truncate("[TIMEOUT]", self.truncate_bytes)
                )
        except Exception as e:
            # Log the exception but still return an error code
            self.logger.error("Local command execution failed", 
                            cmd=" ".join(cmd), 
                            error=str(e),
                            exc_info=True)
            return (127, "", f"Command execution error: {str(e)}")
    
    async def _run_command_docker(self, cmd: List[str], timeout_s: int, cwd: Optional[str] = None) -> Tuple[int, str, str]:
        """Run command in Docker container with timeout using async execution.
        
        Returns: (exit_code, stdout, stderr)
        """
        # Use provided cwd or agent's working directory
        container_cwd = cwd or self.agent_cwd or "/workspace"
        
        try:
            # Wrap command with timeout to ensure it doesn't run forever
            # Using timeout command which returns 124 on timeout
            timeout_cmd = ["timeout", str(timeout_s)] + cmd
            
            # Run exec_run in thread pool to avoid blocking event loop
            loop = asyncio.get_event_loop()
            exec_result = await loop.run_in_executor(
                None,  # Use default executor
                lambda: self.container.exec_run(
                    timeout_cmd,
                    workdir=container_cwd,
                    demux=True,
                    tty=False
                )
            )
            
            exit_code = exec_result.exit_code
            stdout_bytes, stderr_bytes = exec_result.output
            
            stdout = stdout_bytes.decode('utf-8') if stdout_bytes else ""
            stderr = stderr_bytes.decode('utf-8') if stderr_bytes else ""
            
            # Add timeout indicator if command timed out (exit code 124 from timeout command)
            if exit_code == 124:
                stderr = stderr + "\n[TIMEOUT]" if stderr else "[TIMEOUT]"
            
            return (
                exit_code,
                self._truncate(stdout, self.truncate_bytes),
                self._truncate(stderr, self.truncate_bytes)
            )
        except Exception as e:
            # Log the exception but still return an error code
            self.logger.error("Docker command execution failed",
                            cmd=" ".join(cmd),
                            error=str(e),
                            exc_info=True)
            return (127, "", f"Docker execution error: {str(e)}")
    
    async def _responses_create_with_retry(self, **params: Any):
        """Create OpenAI response with retry logic."""
        delay = 0.5
        attempts = self.api_max_retries + 1
        last_err: Optional[Exception] = None
        
        for i in range(attempts):
            try:
                # Log the API call
                self.jsonl_logger.log(
                    request={"params": params, "attempt": i},
                    event="openai_request"
                )
                
                # Use semaphore to limit concurrent API calls
                async with self._api_semaphore:
                    # ABSOLUTELY PROHIBITED FROM SWITCHING THE API - must use Responses API
                    # Always use the async client directly
                    response = await self.openai_client.responses.create(**params)
                
                # Log the successful response with ID
                self.jsonl_logger.log(
                    request={"params": params, "response_id": response.id if hasattr(response, 'id') else None},
                    event="openai_response_success"
                )
                
                return response
            except (APITimeoutError, APIConnectionError, RateLimitError) as e:
                last_err = e
                if i < attempts - 1:
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
                # Log the final failure
                self.jsonl_logger.log(
                    request={"params": params, "error": str(e)},
                    event="openai_response_error"
                )
                raise
            except APIStatusError as e:
                last_err = e
                status = getattr(e, "status_code", None) or getattr(e, "status", None)
                # Handle rate limiting (503 with slow_down error)
                if status == 503 and i < attempts - 1:
                    # For rate limit errors, wait longer
                    wait_time = min(delay * 2, 60)  # Cap at 60 seconds
                    self.logger.warning(f"Rate limited by OpenAI, waiting {wait_time}s before retry")
                    await asyncio.sleep(wait_time)
                    delay = wait_time
                    continue
                elif isinstance(status, int) and status >= 500 and i < attempts - 1:
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
                # Log the final failure
                self.jsonl_logger.log(
                    request={"params": params, "error": str(e)},
                    event="openai_response_error"
                )
                raise
            except Exception as e:
                # Non-retryable
                self.jsonl_logger.log(
                    request={"params": params, "error": str(e)},
                    event="openai_response_error"
                )
                raise
        
        if last_err:
            raise last_err
    
    async def _responses_create_and_execute_tools(self, input_data, previous_response_id=None) -> Tuple[Response, List[TrajectoryItem], List[Dict]]:
        """Create a response and execute any tool calls.
        
        Args:
            input_data: Input for the API (string or list of items)
            previous_response_id: ID of previous response if continuing conversation
            
        Returns: (response, trajectory_items, tool_outputs)
        """           
        params = {
            "model": self.model,
            "input": input_data,
            "instructions": self.system_instructions,
            "stream": False,
            "tool_choice": "auto",
            "store": True,  # Need store=True to use previous_response_id
            "reasoning": {"effort": self.reasoning_effort},  # Add reasoning effort parameter
            "tools": [
                {
                    "type": "function",
                    "name": "shell_run",
                    "description": "Run a shell command and return exit code, stdout, stderr. The cmd parameter must be an array of strings.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "cmd": {
                                "type": "array", 
                                "items": {"type": "string"},
                                "description": "Command and arguments as array of strings"
                            },
                            "timeout_ms": {"type": "integer", "description": "Timeout in milliseconds"},
                        },
                        "required": ["cmd", "timeout_ms"],
                        "additionalProperties": False,
                    },
                    "strict": True,
                }
            ],
        }
        
        # Add previous_response_id if continuing conversation
        if previous_response_id:
            params["previous_response_id"] = previous_response_id
            
        resp: Response = await self._responses_create_with_retry(**params)
        
        trajectory_items: List[TrajectoryItem] = []
        tool_outputs = []  # For sending back to API
        
        # Process response output
        for item in resp.output:
            if isinstance(item, ResponseOutputMessage):
                # Extract text content from message
                text_parts = []
                if item.content:
                    for part in item.content:
                        if isinstance(part, ResponseOutputText):
                            text_parts.append(part.text)
                combined_text = "\n".join([p for p in text_parts if p])
                if combined_text:
                    trajectory_items.append(AssistantMessage(
                        text=combined_text,
                        original={"role": "assistant", "content": combined_text}
                    ))
                    
            elif isinstance(item, ResponseFunctionToolCall):
                # Record the tool call
                try:
                    args = json.loads(item.arguments) if item.arguments else {}
                except json.JSONDecodeError as e:
                    # Don't swallow JSON decode errors
                    self.jsonl_logger.log(
                        request={
                            "error": "Failed to parse tool arguments",
                            "tool_name": item.name,
                            "raw_arguments": item.arguments,
                            "exception": str(e)
                        },
                        event="tool_call_parse_error"
                    )
                    raise RuntimeError(f"Failed to parse tool arguments: {e}")
                    
                trajectory_items.append(ToolCall(
                    tool_name=item.name,
                    arguments=args,
                    original={"call_id": item.call_id, "name": item.name, "arguments": item.arguments}
                ))
                
                # Execute the tool
                if item.name == "shell_run":
                    cmd = args.get("cmd")
                    if not cmd:
                        result = {"exit": 2, "stdout": "", "stderr": f"Missing cmd parameter. Got arguments: {args}"}
                    elif not isinstance(cmd, list) or not all(isinstance(x, str) for x in cmd):
                        result = {"exit": 2, "stdout": "", "stderr": f"Invalid cmd format. Expected array of strings, got: {type(cmd).__name__}"}
                    else:
                        self.logger.debug("Tool call: shell_run", cmd=" ".join(cmd))
                        
                        timeout_ms = args.get("timeout_ms")
                        timeout_s = (
                            self.timeout_s
                            if not isinstance(timeout_ms, int)
                            else max(1, int(timeout_ms / 1000))
                        )
                        # No cwd parameter - always use agent's current working directory
                        cwd = None
                        
                        code, stdout, stderr = await self._run_command(cmd, timeout_s, cwd)
                        result = {"exit": code, "stdout": stdout, "stderr": stderr}
                        
                        self.logger.debug("Tool result", exit_code=code, 
                                         stdout_preview=stdout[:100] if stdout else "")
                else:
                    # Unknown tool
                    result = {"error": f"Unknown tool: {item.name}"}
                
                # Record the tool result (for ALL tools, not just unknown ones!)
                trajectory_items.append(ToolResult(
                    tool_name=item.name,
                    result=result,
                    original={"call_id": item.call_id, "output": json.dumps(result)}
                ))
                
                # Prepare output for API - MUST use call_id not id!
                tool_outputs.append({
                    "type": "function_call_output",
                    "call_id": item.call_id,  # Use call_id, not id!
                    "output": json.dumps(result)
                })
        
        return resp, trajectory_items, tool_outputs
    
    async def setup(self, task: TaskDefinition, task_type_config: dict) -> None:
        """Set up workspace for mini_codex execution.
        
        Args:
            task: Task to execute
            task_type_config: TaskType configuration object
        """
        # First, resolve the task configuration to get setup
        setup, _ = task.resolve_config({task.type: task_type_config})
        
        # Always create workspace directory
        self.workspace_path = Path(tempfile.mkdtemp(prefix="minicodex_"))
        
        # Handle the new composite TaskSetup
        if isinstance(setup, TaskSetup):
            # Extract Docker config if present
            if setup.docker:
                self.docker_config = setup.docker
            
            # Clone git repository BEFORE starting Docker (if configured)
            # This way we clone from host which has SSH keys, then mount into container
            if setup.git_clone:
                await self._clone_repository(setup.git_clone, str(self.workspace_path), is_docker=False)
            
            # Start Docker container if configured (AFTER cloning)
            if self.docker_config:
                await self._start_docker_container()
                # Default working directory in Docker
                self.agent_cwd = "/workspace"
            else:
                # Default working directory locally
                self.agent_cwd = str(self.workspace_path)
        else:
            # No setup needed
            self.agent_cwd = str(self.workspace_path)
    
    async def _run_docker_command(
        self, cmd: list[str], cwd: str, timeout_s: int
    ) -> tuple[int, str, str]:
        """Run a command in Docker container.
        
        Args:
            cmd: Command to run as list of strings
            cwd: Working directory in container
            timeout_s: Timeout in seconds
            
        Returns:
            Tuple of (exit_code, stdout, stderr)
        """
        if not self.container:
            raise RuntimeError("Docker container not started")
        
        # Use the existing _run_command_docker method
        return self._run_command_docker(cmd, timeout_s, cwd)
    
    async def _start_docker_container(self):
        """Start Docker container with workspace mounted."""
        try:
            self.docker_client = docker.from_env()
            
            # Prepare volumes - mount workspace to /workspace in container
            volumes = {
                str(self.workspace_path): {
                    'bind': '/workspace',
                    'mode': 'rw'
                }
            }
            
            # Add any additional volumes from config
            if self.docker_config.volumes:
                volumes.update(self.docker_config.volumes)
            
            self.logger.info("Starting Docker container", 
                           image=self.docker_config.image,
                           workspace=str(self.workspace_path))
            
            # Determine network mode based on config
            # TODO: Defense-in-depth: ideally we would: 1) enable network for git clone/package installs,
            # 2) disable network for agent execution. This provides security isolation and prevents
            # agents from accidentally exfiltrating data or making unintended network calls. For now, we keep it simple.
            network_mode = None if self.docker_config.network_enabled else "none"
            
            # Start container
            self.container = self.docker_client.containers.run(
                self.docker_config.image,
                command="/bin/sh -c 'sleep infinity'",  # Keep container running
                volumes=volumes,
                environment=self.docker_config.env or {},
                working_dir="/workspace",
                network_mode=network_mode,  # None means default (bridge), "none" disables network
                detach=True,
                remove=True,
                stdout=True,
                stderr=True
            )
            
            self.logger.info("Docker container started", container_id=self.container.id[:12])
            
        except Exception as e:
            self.logger.error("Failed to start Docker container", error=str(e))
            # Don't fall back - raise the error so it's handled properly
            raise RuntimeError(f"Failed to start Docker container: {e}") from e
    
    async def run_task(self, task: TaskDefinition, agent_instructions: str) -> Rollout:
        """Execute task using mini_codex.
        
        Args:
            task: Task to execute (contains the task prompt)
            agent_instructions: The instructions being optimized by the optimizer
            
        Returns:
            Rollout with trajectory and files
        """
        # Use provided agent instructions for the OpenAI system instructions
        self.system_instructions = agent_instructions
        if not self.workspace_path:
            raise RuntimeError("Workspace not set up. Call setup() first.")
        
        trajectory: list[TrajectoryItem] = []
        all_outputs = []
        start_time = time.time()
        
        # Save original environment
        original_env = os.environ.copy()
        
        try:
            # Start conversation with user task
            trajectory.append(UserInput(text=task.prompt))
            
            # First call with the user's task
            response, items, tool_outputs = await self._responses_create_and_execute_tools(
                input_data=task.prompt,
                previous_response_id=None
            )
            trajectory.extend(items)
            
            # Collect any assistant messages
            for item in items:
                if isinstance(item, AssistantMessage) and item.text:
                    all_outputs.append(item.text)
            
            # Keep processing tool outputs
            previous_id = response.id
            cycles = 0
            
            while tool_outputs and cycles < self.max_cycles:
                cycles += 1
                # Send tool outputs back with previous_response_id
                response, items, new_tool_outputs = await self._responses_create_and_execute_tools(
                    input_data=tool_outputs,
                    previous_response_id=previous_id
                )
                trajectory.extend(items)
                
                # Collect any assistant messages
                for item in items:
                    if isinstance(item, AssistantMessage) and item.text:
                        all_outputs.append(item.text)
                
                # Update for next iteration
                previous_id = response.id
                tool_outputs = new_tool_outputs
            
            # Combine all outputs as final
            final_output = "\n".join(all_outputs) if all_outputs else ""
            if final_output:
                trajectory.append(FinalOutput(text=final_output))
            
            # Collect files from workspace
            files = self._collect_files_from_workspace()
            
            return Rollout(
                task_id=task.id,
                runner_id=self.runner_id,
                agent_id=f"{self.runner_id}_{uuid.uuid4().hex[:8]}",
                trajectory=trajectory,
                files=files,
                success=True,
                error_message=None,
                cost_usd=0.0,  # Mini codex doesn't track costs
                duration_seconds=time.time() - start_time,
                metadata={
                    "workspace": str(self.workspace_path),
                    "model": self.model
                }
            )
            
        except (APIStatusError, APITimeoutError, APIConnectionError) as e:
            # Re-raise API errors so they're not sent for grading
            raise
        except Exception as e:
            # Log the full exception with traceback
            self.logger.exception("Task execution failed with unexpected error", 
                                 task_id=task.id,
                                 error_type=type(e).__name__)
            # Re-raise to let the caller handle it properly
            raise
        finally:
            # Restore environment
            os.environ.clear()
            os.environ.update(original_env)
    
    def _collect_files_from_workspace(self) -> dict[str, str]:
        """Collect all files from the workspace directory."""
        return collect_workspace_files(self.workspace_path)
    
    async def cleanup(self) -> None:
        """Clean up workspace directory and Docker container."""
        # Stop Docker container if running
        if self.container:
            try:
                self.logger.info("Stopping Docker container", container_id=self.container.id[:12])
                # Just stop the container - it will auto-remove since we created it with remove=True
                self.container.stop(timeout=5)
            except docker.errors.NotFound:
                # Container already removed, that's fine
                self.logger.debug("Container already removed")
            except Exception as e:
                # Log but don't fail cleanup for other errors
                self.logger.warning("Error stopping Docker container", error=str(e))
            self.container = None
        
        # Clean up Docker client
        if self.docker_client:
            try:
                self.docker_client.close()
            except Exception:
                pass
            self.docker_client = None
        
        # Clean up workspace directory
        if self.workspace_path and self.workspace_path.exists():
            try:
                shutil.rmtree(self.workspace_path)
            except Exception as e:
                self.logger.error("Error cleaning up workspace", error=str(e))
            self.workspace_path = None
    
    def get_environment(self) -> RunnerEnvironment | None:
        """Get workspace environment information."""
        if not self.workspace_path:
            return None
        
        return RunnerEnvironment(
            type="workspace_dir",
            data={"path": str(self.workspace_path)}
        )