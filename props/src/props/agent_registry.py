"""Agent registry - manages agent lifecycle and tracking.

WARNING: This module is currently NOT WIRED UP to any runners. It exists as a
skeleton for future sub-agent spawning functionality. See TODOs below.

AgentRegistry provides centralized management for:
- Creating new agent runs (with database records)
- Running agents to completion or interactively
- Tracking active agents
- Restoring agents from database after restart

TODO: This module needs significant work before it can be used:

1. TASK TRACKING: Add asyncio.Task tracking for concurrent agent runs.
   Currently only tracks AgentHandle refs, but can't await/cancel running agents.
   ```python
   _active_tasks: dict[UUID, asyncio.Task]  # To await/cancel
   ```

2. LIFECYCLE INTEGRATION: Integrate with AgentEnvironment context lifecycle.
   The real lifecycle (compositor, Docker container, temp DB user) is managed by
   AgentEnvironment, not the registry. Options:
   - Registry owns AgentEnvironment contexts, or
   - Registry receives lifecycle notifications from environments

3. PARENT-CHILD TRACKING: Add tree tracking for sub-agent hierarchies.
   ```python
   _parent_children: dict[UUID, set[UUID]]  # For cancel_subtree()
   ```

4. WIRE TO RUNNERS: Integrate with run_critic(), grade_critic_run(), etc.
   Each runner would need to register/unregister with the registry.

5. BUDGET-BASED CANCELLATION: For prompt optimizer parallel runs, implement
   cancellation across all running agents when budget exceeded.

See also:
- docs/design/agent-definitions.md "Future Work" section
- Sub-agent spawning (FREEFORM type) design

Usage (when implemented):
    registry = AgentRegistry(workspace_manager=workspace_manager)

    # Create and run interactively (sub-agents)
    handle = await registry.create_agent(
        definition_id="freeform",
        type_config=FreeformTypeConfig(),
        model_client=model_client,
        mcp_client=mcp_client,
        compositor=compositor,
        parent_agent_run_id=None,
    )
    handle.insert_message(UserMessage.text("Hello"))
    result = await handle.run()
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from openai_utils.model import OpenAIModelProto
from props.agent_handle import AgentHandle
from props.agent_types import TypeConfig
from props.agent_workspace import WorkspaceManager
from props.db.models import AgentRun
from props.db.session import get_session

if TYPE_CHECKING:
    from fastmcp.client import Client

    from agent_core.handler import BaseHandler
    from props.docker_env import PropertiesDockerCompositor

logger = logging.getLogger(__name__)


def _create_agent_run_record(
    *, agent_run_id: UUID, definition_id: str, model: str, type_config: TypeConfig, parent_agent_run_id: UUID | None
) -> None:
    """Create agent_runs record in database."""
    with get_session() as session:
        run = AgentRun(
            agent_run_id=agent_run_id,
            agent_definition_id=definition_id,
            parent_agent_run_id=parent_agent_run_id,
            model=model,
            type_config=type_config,
        )
        session.add(run)
        session.commit()
        logger.info(f"Created agent run record: {agent_run_id}")


class AgentRegistry:
    """Manages agent lifecycle - creation, running, and tracking.

    Provides two main workflows:

    1. Run-to-completion: For agents that run autonomously until done
       (critics, graders). Creates agent, runs it, returns result.

    2. Interactive: For agents that exchange messages with a parent
       (sub-agents, freeform). Returns handle for manual message/run cycles.

    Tracks active agents and can restore from database after restart.
    """

    def __init__(self, *, workspace_manager: WorkspaceManager):
        self._workspace_manager = workspace_manager
        self._active_handles: dict[UUID, AgentHandle] = {}

    async def create_agent(
        self,
        *,
        definition_id: str,
        type_config: TypeConfig,
        model_client: OpenAIModelProto,
        mcp_client: Client,
        compositor: PropertiesDockerCompositor,
        parent_agent_run_id: UUID | None,
        handlers: list[BaseHandler] | None = None,
    ) -> AgentHandle:
        """Create a new agent and return its handle for interactive use.

        Creates database record and unpacks definition to workspace.
        Returns handle for insert_message()/run() cycles.
        """
        agent_run_id = uuid4()

        # Create database record
        _create_agent_run_record(
            agent_run_id=agent_run_id,
            definition_id=definition_id,
            model=model_client.model,
            type_config=type_config,
            parent_agent_run_id=parent_agent_run_id,
        )

        # Create AgentHandle - reads system prompt from container via MCP, runs init
        handle = await AgentHandle.create(
            agent_run_id=agent_run_id,
            definition_id=definition_id,
            model_client=model_client,
            mcp_client=mcp_client,
            compositor=compositor,
            handlers=handlers or [],
        )

        self._active_handles[agent_run_id] = handle
        return handle

    def get_active_agent(self, agent_run_id: UUID) -> AgentHandle | None:
        """Get an active agent handle by ID, or None if not found/active."""
        return self._active_handles.get(agent_run_id)

    def list_active_agents(self) -> list[UUID]:
        """List IDs of all active agents."""
        return list(self._active_handles.keys())

    def stop_agent(self, agent_run_id: UUID) -> bool:
        """Remove an agent from active tracking.

        Returns True if agent was found and removed, False otherwise.
        Note: This does not terminate any running agent.run() calls.
        """
        if agent_run_id in self._active_handles:
            del self._active_handles[agent_run_id]
            logger.info(f"Stopped tracking agent: {agent_run_id}")
            return True
        return False

    def stop_all(self) -> int:
        """Remove all agents from active tracking.

        Returns number of agents stopped.
        """
        count = len(self._active_handles)
        self._active_handles.clear()
        logger.info(f"Stopped tracking {count} agents")
        return count
