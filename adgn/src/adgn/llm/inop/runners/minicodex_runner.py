from __future__ import annotations

from contextlib import AsyncExitStack
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
from typing import Any
import uuid

from adgn.llm.inop.clients.logging_openai_client import LoggingOpenAIModel
from adgn.llm.inop.engine.models import (
    AssistantMessage,
    FinalOutput,
    Rollout,
    RunnerEnvironment,
    TaskDefinition,
    TaskType,
    ToolCall,
    ToolResult,
    TrajectoryItem,
    UserInput,
)
from adgn.llm.inop.io.file_utils import collect_workspace_files
from adgn.llm.inop.runners.base import AgentRunner
from adgn.llm.mcp._shared.container_session import ContainerOptions, NetworkMode
from adgn.llm.mcp.docker_exec.server import make_container_exec_mcp
from adgn.llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn.llm.mcp.local_exec.server import make_local_exec_mcp
from adgn.llm.mcp.types import ServerSlotSpec
from adgn.llm.mini_codex.agent import MiniCodex
from adgn.llm.mini_codex.aggregating_handler import AutoHandler
from adgn.llm.mini_codex.event_renderer import DisplayEventsHandler
from adgn.llm.mini_codex.handler import BaseHandler
from adgn.llm.mini_codex.loggers import TranscriptLoggerHandler
from adgn.llm.mini_codex.mcp_manager import McpManager

"""Mini Codex runner that delegates execution to the MiniCodex agent."""


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
        # Optional: allow callers/tests to pass their own handlers
        self._handlers: list[BaseHandler] | None = (
            config.get("handlers") if isinstance(config.get("handlers"), list) else None
        )

    async def setup(
        self,
        task: TaskDefinition,
        task_type_config: dict[str, Any],
    ) -> None:
        # Ensure proper typing for resolve_config: expects dict[str, TaskType]
        typed_map: dict[str, TaskType] = {
            task.type: TaskType.model_validate(task_type_config),
        }
        setup, _ = task.resolve_config(typed_map)

        self.workspace_path = Path(tempfile.mkdtemp(prefix="minicodex_"))

        if setup and setup.git_clone:
            await self._clone_repository(
                setup.git_clone,
                str(self.workspace_path),
                is_docker=False,
            )

        slots = self._build_mcp_slots(setup)

        self._exit_stack = AsyncExitStack()
        self._mcp_manager = await self._exit_stack.enter_async_context(
            McpManager(slots),
        )
        # Per-run transcript directory
        run_dir = Path.cwd() / "logs" / "mini_codex" / "minicodex_runner"
        run_dir = run_dir / f"run_{int(time.time())}_{os.getpid()}"
        run_dir.mkdir(parents=True, exist_ok=True)
        default_handlers: list[BaseHandler] = [
            AutoHandler(),
            DisplayEventsHandler(),
            TranscriptLoggerHandler(run_dir),
        ]
        handlers: list[BaseHandler] = self._handlers or default_handlers
        agent = await MiniCodex.create(
            model=self.model,
            system=None,
            mcp=self._mcp_manager,
            client=self._logging_model,
            reasoning_effort=self.reasoning_effort,
            handlers=handlers,
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
            network_mode = (
                NetworkMode.BRIDGE if setup.docker.network_enabled else NetworkMode.NONE
            )

            def _make_server():
                return make_container_exec_mcp(
                    ContainerOptions(
                        image=setup.docker.image,
                        working_dir="/workspace",
                        volumes=volumes,
                        network_mode=network_mode,
                        environment=setup.docker.env or {},
                    )
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
        )

        trajectory: list[TrajectoryItem] = [UserInput(text=task.prompt)]
        # TODO(mpokorny): Tests needing event capture must pass handlers=[...] with their own capture handler.
        # This runner does not reconstruct events; result.sequence was dropped.
        events_iter: list[dict[str, Any]] = []
        for evt in events_iter:
            kind = evt.get("kind")
            if kind == "assistant_text":
                trajectory.append(
                    AssistantMessage(text=evt.get("text", ""), original=evt),
                )
            elif kind == "tool_call":
                trajectory.append(
                    ToolCall(
                        tool_name=evt.get("name", ""),
                        arguments=evt.get("args", {}),
                        original=evt,
                    ),
                )
            elif kind == "function_call_output":
                raw_output = evt.get("output")
                parsed_output: Any = raw_output
                if isinstance(raw_output, str):
                    try:
                        parsed_output = json.loads(raw_output)
                    except json.JSONDecodeError:
                        parsed_output = raw_output
                trajectory.append(
                    ToolResult(
                        tool_name=evt.get("name", ""),
                        result=parsed_output,
                        original=evt,
                    ),
                )
            elif kind == "tool_error":
                trajectory.append(
                    ToolResult(
                        tool_name=evt.get("name", ""),
                        result=None,
                        error=evt.get("error"),
                        original=evt,
                    ),
                )

        if result.text:
            trajectory.append(FinalOutput(text=result.text))

        assert self.workspace_path is not None, "Workspace path not initialised"
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
            metadata={
                "workspace": str(self.workspace_path) if self.workspace_path else None,
            },
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
