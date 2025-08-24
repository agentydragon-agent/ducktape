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
    DockerSetup,
    FinalOutput,
    GitCloneSetup,
    NoSetup,
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
        
        # Working directory for the agent (may be subdir of workspace)
        self.agent_cwd = None
        
        # Docker configuration - will be set from task setup during setup()
        # TODO: Consider supporting (task, runner) specific Docker configs in the future
        self.docker_config = None
        self.container = None
        self.docker_client = None
        
        # Set up OpenAI client with logging
        self.openai_client = config.get("openai_client")
        if not self.openai_client:
            # Create a default logging client if not provided
            from openai import OpenAI
            log_path = config.get("openai_log_path", Path.cwd() / "minicodex_openai.jsonl")
            self.openai_client = LoggingOpenAIClient(
                openai_client=OpenAI(),
                jsonl_logger=JSONLLogger(log_path)
            )
    
    def _truncate(self, s: str, limit: int) -> str:
        """Truncate string to limit with indicator."""
        if len(s) <= limit:
            return s
        return s[: limit - 12] + "\n[TRUNCATED]"
    
    def _run_command(self, cmd: List[str], timeout_s: int, cwd: Optional[str] = None) -> Tuple[int, str, str]:
        """Run command with timeout, either in Docker container or locally.
        
        Returns: (exit_code, stdout, stderr)
        """
        if self.docker_config and self.container:
            # Run in Docker container
            return self._run_command_docker(cmd, timeout_s, cwd)
        else:
            # Run locally (when docker=null or container not started)
            return self._run_command_local(cmd, timeout_s, cwd)
    
    def _run_command_local(self, cmd: List[str], timeout_s: int, cwd: Optional[str] = None) -> Tuple[int, str, str]:
        """Run command locally with timeout.
        
        Returns: (exit_code, stdout, stderr)
        """
        # Use provided cwd, or agent's working directory
        if cwd is None:
            cwd = self.agent_cwd or str(self.workspace_path)
        
        try:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout_s
            )
            exit_code = result.returncode
            stdout = self._truncate(result.stdout, self.truncate_bytes)
            stderr = self._truncate(result.stderr, self.truncate_bytes)
            
            return (exit_code, stdout, stderr)
        except subprocess.TimeoutExpired as e:
            # Kill and return timeout error
            stdout = e.stdout.decode('utf-8') if e.stdout else ""
            stderr = e.stderr.decode('utf-8') if e.stderr else ""
            return (
                124,
                self._truncate(stdout, self.truncate_bytes),
                self._truncate(stderr + "\n[TIMEOUT]", self.truncate_bytes)
            )
        except Exception as e:
            return (127, "", str(e))
    
    def _run_command_docker(self, cmd: List[str], timeout_s: int, cwd: Optional[str] = None) -> Tuple[int, str, str]:
        """Run command in Docker container with timeout.
        
        Returns: (exit_code, stdout, stderr)
        """
        # Use provided cwd or agent's working directory
        container_cwd = cwd or self.agent_cwd or "/workspace"
        
        try:
            # Execute command in container
            exec_result = self.container.exec_run(
                cmd,
                workdir=container_cwd,
                demux=True,
                tty=False
            )
            
            exit_code = exec_result.exit_code
            stdout_bytes, stderr_bytes = exec_result.output
            
            stdout = stdout_bytes.decode('utf-8') if stdout_bytes else ""
            stderr = stderr_bytes.decode('utf-8') if stderr_bytes else ""
            
            return (
                exit_code,
                self._truncate(stdout, self.truncate_bytes),
                self._truncate(stderr, self.truncate_bytes)
            )
        except Exception as e:
            return (127, "", f"Docker execution error: {str(e)}")
    
    def _responses_create_with_retry(self, **params: Any):
        """Create OpenAI response with retry logic."""
        delay = 0.5
        attempts = self.api_max_retries + 1
        last_err: Optional[Exception] = None
        
        for i in range(attempts):
            try:
                # Log the API call
                self.openai_client.jsonl_logger.log(
                    request={"params": params, "attempt": i},
                    event="openai_request"
                )
                # ABSOLUTELY PROHIBITED FROM SWITCHING THE API - must use Responses API
                response = self.openai_client.openai_client.responses.create(**params)
                # Log the successful response with ID
                self.openai_client.jsonl_logger.log(
                    request={"params": params, "response_id": response.id if hasattr(response, 'id') else None},
                    event="openai_response_success"
                )
                
                return response
            except (APITimeoutError, APIConnectionError, RateLimitError) as e:
                last_err = e
                if i < attempts - 1:
                    time.sleep(delay)
                    delay *= 2
                    continue
                # Log the final failure
                self.openai_client.jsonl_logger.log(
                    request={"params": params, "error": str(e)},
                    event="openai_response_error"
                )
                raise
            except APIStatusError as e:
                last_err = e
                status = getattr(e, "status_code", None) or getattr(e, "status", None)
                if isinstance(status, int) and status >= 500 and i < attempts - 1:
                    time.sleep(delay)
                    delay *= 2
                    continue
                # Log the final failure
                self.openai_client.jsonl_logger.log(
                    request={"params": params, "error": str(e)},
                    event="openai_response_error"
                )
                raise
            except Exception as e:
                # Non-retryable
                self.openai_client.jsonl_logger.log(
                    request={"params": params, "error": str(e)},
                    event="openai_response_error"
                )
                raise
        
        if last_err:
            raise last_err
    
    def _responses_create_and_execute_tools(self, input_data, previous_response_id=None) -> Tuple[Response, List[TrajectoryItem], List[Dict]]:
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
            
        resp: Response = self._responses_create_with_retry(**params)
        
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
                    self.openai_client.jsonl_logger.log(
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
                        
                        code, stdout, stderr = self._run_command(cmd, timeout_s, cwd)
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
        
        # Check if task specifies Docker setup
        if isinstance(setup, DockerSetup):
            self.docker_config = setup
        
        # Start Docker container if configured
        if self.docker_config:
            await self._start_docker_container()
            # Default working directory in Docker
            self.agent_cwd = "/workspace"
        else:
            # Default working directory locally
            self.agent_cwd = str(self.workspace_path)
        
        # Clone git repository if configured
        if isinstance(setup, GitCloneSetup):
            # Clone directly into workspace (no subdir support - agent can navigate)
            if self.docker_config:
                await self._clone_repository(setup, "/workspace", is_docker=True)
            else:
                await self._clone_repository(setup, str(self.workspace_path), is_docker=False)
    
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
            
            # Start container
            self.container = self.docker_client.containers.run(
                self.docker_config.image,
                command="/bin/sh -c 'sleep infinity'",  # Keep container running
                volumes=volumes,
                environment=self.docker_config.env or {},
                working_dir="/workspace",
                detach=True,
                remove=True,
                stdout=True,
                stderr=True
            )
            
            self.logger.info("Docker container started", container_id=self.container.id[:12])
            
        except Exception as e:
            self.logger.error("Failed to start Docker container", error=str(e))
            # Fall back to local execution
            self.docker_config = None
            self.container = None
    
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
            response, items, tool_outputs = self._responses_create_and_execute_tools(
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
                response, items, new_tool_outputs = self._responses_create_and_execute_tools(
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
            
        except Exception as e:
            # Re-raise API errors so they're not sent for grading
            if isinstance(e, (APIStatusError, APITimeoutError, APIConnectionError)):
                raise
            # Return error rollout for other errors
            return Rollout(
                task_id=task.id,
                runner_id=self.runner_id,
                agent_id=f"{self.runner_id}_{uuid.uuid4().hex[:8]}",
                trajectory=trajectory,
                files={},
                success=False,
                error_message=str(e),
                cost_usd=0.0,
                duration_seconds=0.0,
                metadata={"error": str(e)}
            )
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