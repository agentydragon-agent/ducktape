"""Agent handle - wraps Agent with definition-based image and system prompt.

AgentHandle provides a similar interface to Agent (insert_message, run) but manages:
- Loading agent definition from database
- Running init script and using its output as system prompt
- System message injection

Usage:
    async with AgentEnvironment(...) as comp:
        handle = await AgentHandle.create(
            agent_run_id=run_id,
            definition_id="critic",
            model_client=openai_client,
            mcp_client=mcp_client,
            compositor=comp,
            handlers=[],
        )
        handle.insert_message(UserMessage.text("Review this code"))
        result = await handle.run()

Note: The Docker image is built from the definition archive by AgentEnvironment.
The /init script output becomes the system prompt.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
import logging
from typing import TYPE_CHECKING
from uuid import UUID

from adgn.agent.bootstrap import run_init_script
from agent_core.agent import Agent, AgentResult, Message
from agent_core.handler import BaseHandler, CaptureTextHandler
from agent_core.loop_control import AllowAnyToolOrTextMessage
from openai_utils.model import SystemMessage
from openai_utils.types import ReasoningSummary
from props.db.models import AgentDefinition
from props.db.session import get_session
from props.db_event_handler import DatabaseEventHandler

if TYPE_CHECKING:
    from fastmcp.client import Client

    from openai_utils.model import OpenAIModelProto
    from props.docker_env import PropertiesDockerCompositor

logger = logging.getLogger(__name__)


def load_definition_archive(definition_id: str) -> bytes:
    """Load agent definition archive from database.

    Returns just the archive bytes since returning the ORM object would
    cause DetachedInstanceError when accessed outside the session.
    """
    with get_session() as session:
        definition = session.get(AgentDefinition, definition_id)
        if not definition:
            raise ValueError(f"Agent definition not found: {definition_id}")
        return definition.archive


@dataclass
class AgentHandle:
    """Handle to a running agent with transcript management.

    Provides Agent-like interface (insert_message, run) while managing:
    - Container lifecycle
    - System message injection from /init output

    Use create() classmethod to construct.
    """

    agent_run_id: UUID
    definition_id: str
    agent: Agent
    compositor: PropertiesDockerCompositor
    text_capture: CaptureTextHandler
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def insert_message(self, message: Message) -> None:
        """Insert a message into the agent's transcript.

        Same semantics as Agent.insert_message() - messages are added to
        the conversation history but don't trigger handlers until run().
        """
        self.agent.insert_message(message)

    async def run(self) -> AgentResult:
        """Run the agent loop until completion or text response.

        For agents using CaptureTextHandler, this returns after the agent
        produces a text message. For run-to-completion agents, this returns
        after the agent finishes (submit tool, max turns, etc.).

        Turn limits are controlled by MaxTurnsHandler passed to create().

        Thread-safe: only one run() call can execute at a time.
        """
        async with self._lock:
            return await self.agent.run()

    @classmethod
    async def create(
        cls,
        *,
        agent_run_id: UUID,
        definition_id: str,
        model_client: OpenAIModelProto,
        mcp_client: Client,
        compositor: PropertiesDockerCompositor,
        handlers: list[BaseHandler],
        dynamic_instructions: Callable[[], Awaitable[str]] | None = None,
        parallel_tool_calls: bool = False,
        reasoning_summary: ReasoningSummary | None = None,
    ) -> AgentHandle:
        """Create an AgentHandle with system prompt from /init output.

        Args:
            agent_run_id: UUID for this agent run (used for DB tracking)
            definition_id: ID of the agent definition (for logging/tracking)
            model_client: OpenAI-compatible model client
            mcp_client: FastMCP client connected to compositor
            compositor: MCP compositor with mounted Docker runtime server (has .runtime attribute)
            handlers: Additional handlers beyond the defaults (DatabaseEventHandler, CaptureTextHandler)
            dynamic_instructions: Optional callable that returns dynamic instructions string
            parallel_tool_calls: Whether to allow parallel tool calls (default False)
            reasoning_summary: Optional reasoning summary mode for the agent

        Returns:
            AgentHandle ready for insert_message() and run() calls.

        Raises:
            InitFailedError: If init script fails
        """
        # 1. Run init script - its stdout becomes the system prompt
        system_prompt = await run_init_script(mcp_client, compositor.runtime)
        logger.debug(f"Init script returned {len(system_prompt)} bytes")

        # 2. Build handlers - start with defaults
        text_capture = CaptureTextHandler()
        all_handlers: list[BaseHandler] = [DatabaseEventHandler(agent_run_id=agent_run_id), text_capture]

        # Add caller-provided handlers
        all_handlers.extend(handlers)

        # 3. Create Agent with optional customization
        agent = await Agent.create(
            mcp_client=mcp_client,
            client=model_client,
            handlers=all_handlers,
            tool_policy=AllowAnyToolOrTextMessage(),
            dynamic_instructions=dynamic_instructions,
            parallel_tool_calls=parallel_tool_calls,
            reasoning_summary=reasoning_summary,
        )

        # 4. Insert system message from init output
        if system_prompt:
            agent.insert_message(SystemMessage.text(system_prompt))

        return cls(
            agent_run_id=agent_run_id,
            definition_id=definition_id,
            agent=agent,
            compositor=compositor,
            text_capture=text_capture,
        )

    def get_captured_text(self) -> str | None:
        """Get captured text if available, without consuming it.

        Returns None if no text was captured yet.
        """
        if self.text_capture.has_text:
            return self.text_capture._captured
        return None

    def take_captured_text(self) -> str:
        """Take captured text, clearing the capture state.

        Raises ValueError if no text was captured.
        """
        return self.text_capture.take()
