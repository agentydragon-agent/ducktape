"""Mini Codex runner that delegates execution to the MiniCodex agent."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import uuid
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from adgn_llm.inop.clients.logging_openai_client import (
    LoggingOpenAIModel,
)
from adgn_llm.inop.engine.models import (
    AssistantMessage,
    FinalOutput,
    Rollout,
    RunnerEnvironment,
    TaskDefinition,
    ToolCall,
    ToolResult,
    TrajectoryItem,
    UserInput,
)
from adgn_llm.inop.io.file_utils import collect_workspace_files
from adgn_llm.inop.runners.base import AgentRunner
from adgn_llm.mcp._shared.container_session import NetworkMode
from adgn_llm.mcp.docker_exec.server import make_container_exec_mcp
from adgn_llm.mcp.inproc_utils import make_inproc_slot_spec
from adgn_llm.mini_codex.agent import MiniCodex
from adgn_llm.mcp.local_exec.server import make_local_exec_mcp
from adgn_llm.mini_codex.mcp_manager import McpManager, ServerSlotSpec


class MiniCodexRunner(AgentRunner):
    """Runner that executes tasks via the MiniCodex agent."""

    def __init__(
        self,
        runner_id: str,
        config: dict[str, Any],
        *,
        openai_model: LoggingOpenAIModel,
    ) -> None:
        super().__init__(runner_id, config)
        self.model = config.get("model", openai_model.model)
        self.reasoning_effort = config.get("reasoning_effort")
        self.workspace_path: Path | None = None
        self._exit_stack: AsyncExitStack | None = None
        self._agent: MiniCodex | None = None
        self._mcp_manager: McpManager | None = None
        self._logging_model = openai_model

    async def setup(self, task: TaskDefinition, task_type_config: dict) -> None:
        setup, _ = task.resolve_config({task.type: task_type_config})

        self.workspace_path = Path(tempfile.mkdtemp(prefix="minicodex_"))

        if setup and setup.git_clone:
            await self._clone_repository(
                setup.git_clone,
                str(self.workspace_path),
                is_docker=False,
            )

        slots = self._build_mcp_slots(setup)

        self._exit_stack = AsyncExitStack()
        self._mcp_manager = await self._exit_stack.enter_async_context(McpManager(slots))
        agent = await MiniCodex.create(
            model=self.model,
            system=None,
            mcp=self._mcp_manager,
            client=self._logging_model.openai_client.openai_client,
            reasoning_effort=self.reasoning_effort,
        )
        self._agent = await self._exit_stack.enter_async_context(agent)

    def _build_mcp_slots(self, setup) -> dict[str, ServerSlotSpec]:
        if not self.workspace_path:
            raise RuntimeError("Workspace not initialised")

        if setup and setup.docker:
            volumes: dict[str, dict[str, str]] = {
                str(self.workspace_path): {"bind": "/workspace", "mode": "rw"},
            }
            for host_path, spec in (setup.docker.volumes or {}).items():
                if isinstance(spec, dict):
                    volumes[str(host_path)] = spec
            network_mode = NetworkMode.BRIDGE if setup.docker.network_enabled else NetworkMode.NONE

            def _make_server():
                return make_container_exec_mcp(
                    image=setup.docker.image,
                    working_dir="/workspace",
                    volumes=volumes,
                    network_mode=network_mode,
                    environment=setup.docker.env or {},
                )

            spec = make_inproc_slot_spec(_make_server())
            return {"container": spec}

        sandbox_enabled = True
        if setup and setup.sandbox:
            sandbox_enabled = setup.sandbox.enabled
        if os.getenv("DUCK_ALLOW_UNSANDBOXED") == "1":
            sandbox_enabled = False

        def _make_server_local():
            return make_local_exec_mcp(
                name="local",
                default_cwd=str(self.workspace_path),
                sandbox_enabled=sandbox_enabled,
            )

        spec = make_inproc_slot_spec(_make_server_local())
        return {"local": spec}

    async def run_task(self, task: TaskDefinition, agent_instructions: str) -> Rollout:
        if not self._agent:
            raise RuntimeError("Runner not initialised; call setup() first")

        self._agent.set_system_instructions(agent_instructions)

        start_time = time.time()
        result = await self._agent.run(
            user_text=task.prompt,
            require_at_least_one_tool=True,
        )

        trajectory: list[TrajectoryItem] = [UserInput(text=task.prompt)]
        for event in result.sequence:
            kind = event.get("kind")
            if kind == "assistant_text":
                trajectory.append(
                    AssistantMessage(text=event.get("text", ""), original=event),
                )
            elif kind == "tool_call":
                trajectory.append(
                    ToolCall(
                        tool_name=event.get("name", ""),
                        arguments=event.get("args", {}),
                        original=event,
                    ),
                )
            elif kind == "function_call_output":
                raw_output = event.get("output")
                parsed_output: Any = raw_output
                if isinstance(raw_output, str):
                    try:
                        parsed_output = json.loads(raw_output)
                    except json.JSONDecodeError:
                        parsed_output = raw_output
                trajectory.append(
                    ToolResult(
                        tool_name=event.get("name", ""),
                        result=parsed_output,
                        original=event,
                    ),
                )
            elif kind == "tool_error":
                trajectory.append(
                    ToolResult(
                        tool_name=event.get("name", ""),
                        result=None,
                        error=event.get("error"),
                        original=event,
                    ),
                )

        if result.text:
            trajectory.append(FinalOutput(text=result.text))

        files = collect_workspace_files(self.workspace_path)

        return Rollout(
            task_id=task.id,
            runner_id=self.runner_id,
            agent_id=f"{self.runner_id}_{uuid.uuid4().hex[:8]}",
            trajectory=trajectory,
            files=files,
            success=True,
            error_message=None,
            cost_usd=0.0,
            duration_seconds=time.time() - start_time,
            metadata={"workspace": str(self.workspace_path) if self.workspace_path else None},
        )

    async def cleanup(self) -> None:
        if self._exit_stack:
            await self._exit_stack.aclose()
            self._exit_stack = None
        if self.workspace_path and self.workspace_path.exists():
            shutil.rmtree(self.workspace_path)
            self.workspace_path = None

    def get_environment(self) -> RunnerEnvironment | None:
        if not self.workspace_path:
            return None
        return RunnerEnvironment(
            type="workspace_dir",
            data={"path": str(self.workspace_path)},
        )
