"""Builder functions for creating agent infrastructure using the new architecture.

This module provides builder functions that replace the old AgentContainer
with the new MCPInfrastructure + LocalAgentRuntime architecture.
"""

from __future__ import annotations

from collections.abc import Callable

from docker import DockerClient
from fastmcp.mcp_config import MCPConfig

from adgn.agent.persist.sqlite import SQLitePersistence
from adgn.agent.runtime.infrastructure import MCPInfrastructure
from adgn.agent.runtime.local_runtime import LocalAgentRuntime
from adgn.agent.runtime.running import RunningInfrastructure
from adgn.agent.runtime.sidecars import SidecarBundle
from adgn.agent.server.bus import ServerBus
from adgn.agent.server.runtime import ConnectionManager
from adgn.openai_utils.model import OpenAIModelProto


async def build_local_agent(
    *,
    agent_id: str,
    mcp_config: MCPConfig,
    persistence: SQLitePersistence,
    model: str,
    client_factory: Callable[[str], OpenAIModelProto],
    docker_client: DockerClient,
    with_ui: bool = True,
    ui_bus: ServerBus | None = None,
    connection_manager: ConnectionManager | None = None,
    system_override: str | None = None,
    initial_policy: str | None = None,
) -> tuple[RunningInfrastructure, LocalAgentRuntime, ServerBus | None, ConnectionManager | None]:
    """Example:
        from adgn.openai_utils.client_factory import build_client

        def client_factory(model: str):
            return build_client(model, enable_debug_logging=True)

        running, runtime, ui_bus, conn_mgr = await build_local_agent(
            agent_id="my-agent",
            mcp_config=config,
            persistence=persistence,
            model="o4-mini",
            client_factory=client_factory,
            docker_client=docker.from_env(),
            with_ui=True,
            ui_bus=ui_bus,
        )

        # Use the agent
        result = await runtime.run("Hello!")

        # Cleanup
        await runtime.close()
        await running.close()
    """
    # Validate UI requirements and create connection manager if needed
    if with_ui:
        if ui_bus is None:
            raise ValueError("ui_bus required when with_ui=True")
        if connection_manager is None:
            connection_manager = ConnectionManager()

    # Create infrastructure builder
    builder = MCPInfrastructure(
        agent_id=agent_id,
        persistence=persistence,
        docker_client=docker_client,
        initial_policy=initial_policy,
        connection_manager=connection_manager,
    )

    # Start core infrastructure
    running = await builder.start(mcp_config)

    # Attach sidecars
    if with_ui:
        assert ui_bus is not None
        bundle = SidecarBundle.for_local_agent(ui_bus=ui_bus)
    else:
        # No UI - just chat and loop
        bundle = SidecarBundle(
            sidecars=[
                # ChatSidecar(),  # TODO: Add when needed
                # LoopControlSidecar(),  # TODO: Add when needed
            ]
        )
    await bundle.attach_all(running)

    # Create local agent runtime with UI components
    runtime = LocalAgentRuntime(
        running=running,
        model=model,
        client_factory=client_factory,
        system_override=system_override,
        ui_bus=ui_bus,
        connection_manager=connection_manager,
    )

    await runtime.start()

    return (running, runtime, ui_bus, connection_manager)
