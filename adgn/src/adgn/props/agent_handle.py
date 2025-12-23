"""Agent handle - wraps Agent with definition loading and workspace management.

AgentHandle provides a similar interface to Agent (insert_message, run) but manages:
- Loading definition from database
- Unpacking to persistent workspace
- Executing init script via BootstrapHandler (if present)
- System message from AGENT.md

Usage:
    async with PropertiesDockerCompositorHTTP(...) as comp:
        handle = await AgentHandle.create(
            agent_run_id=run_id,
            definition_id="critic",
            model_client=openai_client,
            mcp_client=mcp_client,
            compositor=comp,
            workspace_manager=WorkspaceManager.from_env(),
            handlers=[],
        )
        handle.insert_message(UserMessage.text("Review this code"))
        result = await handle.run()
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
import io
import logging
from pathlib import Path
import tarfile
from typing import TYPE_CHECKING
from uuid import UUID

from adgn.agent.agent import Agent, AgentResult, Message
from adgn.agent.bootstrap import TypedBootstrapBuilder, docker_exec_call
from adgn.agent.db_event_handler import DatabaseEventHandler
from adgn.agent.handler import BaseHandler, BootstrapHandler, CaptureTextHandler
from adgn.agent.loop_control import AllowAnyToolOrTextMessage
from adgn.openai_utils.model import SystemMessage
from adgn.openai_utils.types import ReasoningSummary
from adgn.props.agent_workspace import WorkspaceManager
from adgn.props.db import get_session
from adgn.props.db.models import AgentDefinition

if TYPE_CHECKING:
    from fastmcp.client import Client

    from adgn.openai_utils.model import OpenAIModelProto
    from adgn.props.docker_env import PropertiesDockerCompositor

logger = logging.getLogger(__name__)


# Init scripts print models.py (~1000 lines), helper code, and do DB verification.
# 15 seconds is enough for Python startup + printing + DB connection.
INIT_BOOTSTRAP_TIMEOUT_MS = 15_000


def make_init_bootstrap_handler(compositor: PropertiesDockerCompositor) -> BootstrapHandler:
    """Create a BootstrapHandler that runs ./init in the container.

    This is the standard bootstrap pattern for all agents using agent definitions.
    The init script is expected to be at /workspace/init in the container (mounted
    from the unpacked definition workspace).

    Args:
        compositor: Docker compositor with mounted runtime server (has .runtime attribute)

    Returns:
        BootstrapHandler configured to run ./init
    """
    builder = TypedBootstrapBuilder.for_server(compositor.runtime.server)
    init_call = docker_exec_call(builder, compositor.runtime, cmd=["./init"], timeout_ms=INIT_BOOTSTRAP_TIMEOUT_MS)
    return BootstrapHandler(init_call)


def _unpack_definition(archive: bytes, target_dir: Path) -> None:
    """Unpack tar archive to target directory."""
    target_dir.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO(archive)
    with tarfile.open(fileobj=buffer, mode="r") as tar:
        tar.extractall(target_dir, filter="data")


def _load_definition_archive(definition_id: str) -> bytes:
    """Load agent definition archive from database.

    Returns just the archive bytes since returning the ORM object would
    cause DetachedInstanceError when accessed outside the session.
    """
    with get_session() as session:
        definition = session.get(AgentDefinition, definition_id)
        if not definition:
            raise ValueError(f"Agent definition not found: {definition_id}")
        # Return archive bytes (loaded within session)
        return definition.archive


def ensure_definition_unpacked(definition_id: str, workspace: Path) -> None:
    """Ensure agent definition is unpacked to workspace directory.

    This should be called BEFORE starting a container that mounts the workspace,
    since Docker mount creates the directory as root if it doesn't exist,
    which would prevent subsequent unpacking.

    Args:
        definition_id: Agent definition ID to load from database
        workspace: Target workspace directory

    Raises:
        ValueError: If definition not found or AGENT.md missing after unpack
    """
    # Check if already unpacked (has AGENT.md)
    agent_md_path = workspace / "AGENT.md"
    if agent_md_path.exists():
        logger.info(f"Definition {definition_id} already unpacked at {workspace}")
        return

    # Load and unpack definition
    archive = _load_definition_archive(definition_id)
    _unpack_definition(archive, workspace)
    logger.info(f"Unpacked definition {definition_id} to {workspace}")

    # Verify AGENT.md exists
    if not agent_md_path.exists():
        raise ValueError(f"No AGENT.md found after unpacking {definition_id} - archive is invalid")


@dataclass
class AgentHandle:
    """Handle to a running agent with transcript management.

    Provides Agent-like interface (insert_message, run) while managing:
    - Definition loading and workspace unpacking
    - Container lifecycle
    - System message injection from AGENT.md

    Use create() classmethod to construct.
    """

    agent_run_id: UUID
    definition_id: str
    workspace: Path
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
        workspace_manager: WorkspaceManager,
        handlers: list[BaseHandler],
        dynamic_instructions: Callable[[], Awaitable[str]] | None = None,
        parallel_tool_calls: bool = False,
        reasoning_summary: ReasoningSummary | None = None,
    ) -> AgentHandle:
        """Create an AgentHandle with definition loaded and workspace set up.

        Args:
            agent_run_id: UUID for this agent run (used for workspace path and DB tracking)
            definition_id: ID of the agent definition to load from database
            model_client: OpenAI-compatible model client
            mcp_client: FastMCP client connected to compositor
            compositor: MCP compositor with mounted Docker runtime server (has .runtime attribute)
            workspace_manager: Workspace manager for agent workspace paths
            handlers: Additional handlers beyond the defaults (DatabaseEventHandler, CaptureTextHandler)
            dynamic_instructions: Optional callable that returns dynamic instructions string
            parallel_tool_calls: Whether to allow parallel tool calls (default False)
            reasoning_summary: Optional reasoning summary mode for the agent

        Returns:
            AgentHandle ready for insert_message() and run() calls.

        Raises:
            ValueError: If definition not found
            InitFailedError: If init script fails
        """
        # 1. Unpack to persistent workspace (if not already unpacked)
        workspace = workspace_manager.get_path(agent_run_id)
        agent_md_path = workspace / "AGENT.md"
        if not agent_md_path.exists():
            # Load and unpack definition
            archive = _load_definition_archive(definition_id)
            workspace.mkdir(parents=True, exist_ok=True)
            _unpack_definition(archive, workspace)
            logger.info(f"Unpacked definition {definition_id} to {workspace}")

        # 3. Read system prompt from AGENT.md (required)
        agent_md_path = workspace / "AGENT.md"
        if not agent_md_path.exists():
            raise ValueError(f"No AGENT.md found in {workspace} - agent definition is invalid")
        system_prompt = agent_md_path.read_text()

        # 4. Build handlers - start with defaults
        text_capture = CaptureTextHandler()
        all_handlers: list[BaseHandler] = [DatabaseEventHandler(agent_run_id=agent_run_id), text_capture]

        # 5. Add BootstrapHandler for init script execution
        bootstrap_handler = make_init_bootstrap_handler(compositor)
        # Insert at beginning so init runs before other handlers
        all_handlers.insert(0, bootstrap_handler)

        # Add caller-provided handlers
        all_handlers.extend(handlers)

        # 6. Create Agent with optional customization
        agent = await Agent.create(
            mcp_client=mcp_client,
            client=model_client,
            handlers=all_handlers,
            tool_policy=AllowAnyToolOrTextMessage(),
            dynamic_instructions=dynamic_instructions,
            parallel_tool_calls=parallel_tool_calls,
            reasoning_summary=reasoning_summary,
        )

        # 7. Insert system message from AGENT.md (immutable in transcript)
        if system_prompt:
            agent.insert_message(SystemMessage.text(system_prompt))

        return cls(
            agent_run_id=agent_run_id,
            definition_id=definition_id,
            workspace=workspace,
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
