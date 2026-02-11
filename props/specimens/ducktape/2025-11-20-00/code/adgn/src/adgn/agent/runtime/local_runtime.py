"""LocalAgentRuntime - wraps RunningInfrastructure with MiniCodex agent.

This module provides LocalAgentRuntime, which consumes RunningInfrastructure
and adds:
- MiniCodex agent (OpenAI Responses API)
- AgentSession (run/event management)
- Message handlers
- Loop control server

This is the "client" layer on top of the "service" layer (RunningInfrastructure).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
import logging

from adgn.agent.agent import AgentResult, MiniCodex
from adgn.agent.handler import BaseHandler
from adgn.agent.runtime.handlers import build_handlers
from adgn.agent.runtime.running import RunningInfrastructure
from adgn.agent.server.rendering import render_compositor_instructions
from adgn.agent.server.runtime import AgentSession
from adgn.agent.server.system_message import get_ui_system_message
from adgn.mcp.compositor.clients import CompositorMetaClient
from adgn.openai_utils.model import OpenAIModelProto
from adgn.openai_utils.types import ReasoningEffort, ReasoningSummary

logger = logging.getLogger(__name__)


class LocalAgentRuntime:
    """Consumes RunningInfrastructure's compositor_client and adds:
    - MiniCodex agent (OpenAI Responses API)
    - AgentSession (run/event management)
    - UI integration (WebSocket protocol)
    - Loop control server

    Example:
        from adgn.openai_utils.client_factory import build_client

        def client_factory(model: str):
            return build_client(model, enable_debug_logging=True)

        # Create infrastructure and attach sidecars
        infrastructure = MCPInfrastructure(...)
        running = await infrastructure.start(mcp_config)
        await running.attach_sidecar(UISidecar(ui_bus))
        await running.attach_sidecar(ChatSidecar())
        await running.attach_sidecar(LoopControlSidecar())

        # Create runtime
        runtime = LocalAgentRuntime(
            running=running,
            model="o4-mini",
            client_factory=client_factory,
        )
        await runtime.start()

        # Run agent
        result = await runtime.run("Hello!")
    """

    def __init__(
        self,
        running: RunningInfrastructure,
        model: str,
        client_factory: Callable[[str], OpenAIModelProto],
        system_override: str | None = None,
        reasoning_effort: ReasoningEffort | None = None,
        reasoning_summary: ReasoningSummary | None = None,
        parallel_tool_calls: bool = True,
        extra_handlers: Iterable[BaseHandler] | None = None,
        ui_bus=None,
        connection_manager=None,
    ):
        self.running = running
        self.model = model
        self._client_factory = client_factory
        self._system_override = system_override
        self._reasoning_effort = reasoning_effort
        self._reasoning_summary = reasoning_summary
        self._parallel_tool_calls = parallel_tool_calls
        self._extra_handlers = list(extra_handlers or [])
        self._ui_bus = ui_bus
        self._connection_manager = connection_manager

        # Initialized by start()
        self.session: AgentSession | None = None
        self.agent: MiniCodex | None = None

    async def start(self) -> None:
        # Create session with UI components if provided
        sess = AgentSession(
            manager=self._connection_manager,
            approval_hub=self.running.approval_hub,
            persistence=self.running.approval_engine.persistence,
            agent_id=self.running.agent_id,
            ui_bus=self._ui_bus,
            approval_engine=self.running.approval_engine,
        )

        # LLM client
        client = self._client_factory(self.model)

        # Define run ID helper
        def _get_run_id():
            return sess.active_run.run_id if sess.active_run else None

        # Build handlers
        handlers, persist_handler = build_handlers(
            poll_notifications=self.running.notifications_buffer.poll,
            manager=self._connection_manager,
            persistence=self.running.approval_engine.persistence,
            approval_engine=self.running.approval_engine,
            approval_hub=self.running.approval_hub,
            get_run_id=_get_run_id,
            agent_id=self.running.agent_id,
            ui_bus=self._ui_bus,
        )

        # Add extra handlers if provided
        all_handlers = list(handlers) + self._extra_handlers

        # Set persist handler on session
        sess.set_persist_handler(persist_handler)

        # Compose base system text and dynamic instruction provider
        base_system = self._system_override or str(get_ui_system_message())

        async def _dynamic_instructions() -> str:
            """Dynamically generate instructions from compositor state."""
            meta = CompositorMetaClient(self.running.compositor_client)
            states = await meta.list_states()
            text: str = render_compositor_instructions(states)
            return text

        # Create agent
        agent = await MiniCodex.create(
            model=self.model,
            mcp_client=self.running.compositor_client,
            system=base_system,
            client=client,
            handlers=all_handlers,
            dynamic_instructions=_dynamic_instructions,
            reasoning_effort=self._reasoning_effort,
            reasoning_summary=self._reasoning_summary,
            parallel_tool_calls=self._parallel_tool_calls,
        )

        # Store system used for persisted run metadata
        sess.attach_agent(agent, model=self.model, system=base_system)

        # Store references
        self.session = sess
        self.agent = agent

    async def run(self, user_text: str) -> AgentResult:
        """Raises RuntimeError if agent not started."""
        if self.agent is None:
            raise RuntimeError("agent not started - call start() first")

        return await self.agent.run(user_text)

    async def close(self) -> None:
        """Does NOT close the underlying RunningInfrastructure.
        Call running.close() separately if needed.
        """
        if self.session is not None:
            await self.session.cancel_active_run()
