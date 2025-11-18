"""CLI entry point for HTTP MCP Bridge.

Exposes RunningInfrastructure (Compositor + Policy Gateway) as an HTTP MCP server
that external agents can connect to.

Usage:
    adgn-mcp-bridge serve --agent-id external-chatgpt \\
        --db-path ./bridge.db \\
        --mcp-config ./docker-exec.json \\
        --host 127.0.0.1 --port 8080
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import click
import docker
from fastmcp.mcp_config import MCPConfig
from platformdirs import user_data_dir

from adgn.agent.persist.sqlite import SQLitePersistence
from adgn.agent.runtime.infrastructure import MCPInfrastructure
from adgn.agent.runtime.sidecars import SidecarBundle

logger = logging.getLogger(__name__)

# Default database path in XDG user data directory
DEFAULT_DB_PATH = Path(user_data_dir("adgn", "agentydragon")) / "mcp-bridge.db"


@click.group()
def cli():
    """HTTP MCP Bridge - expose policy-gated infrastructure to external agents."""
    pass


@cli.command()
@click.option("--agent-id", required=True, help="Agent identifier (e.g., 'external-chatgpt')")
@click.option(
    "--db-path",
    type=Path,
    default=DEFAULT_DB_PATH,
    help=f"SQLite database path (default: {DEFAULT_DB_PATH})",
)
@click.option(
    "--mcp-config",
    type=Path,
    help="Path to .mcp.json config (servers to mount, e.g., docker exec with repo mount)",
)
@click.option("--host", default="127.0.0.1", help="Bind host")
@click.option("--port", type=int, default=8080, help="Bind port")
@click.option("--initial-policy", type=Path, help="Path to initial approval policy (Python file)")
def serve(
    agent_id: str,
    db_path: Path,
    mcp_config: Path | None,
    host: str,
    port: int,
    initial_policy: Path | None,
):
    """Start HTTP MCP Bridge server.

    The server exposes a Compositor (FastMCP server) over HTTP/SSE transport.
    External agents connect via MCP-over-HTTP and get policy-gated access to tools.

    Example:
        # Minimal (no docker exec)
        adgn-mcp-bridge serve --agent-id external-agent

        # With repo-mounted docker exec
        adgn-mcp-bridge serve --agent-id external-chatgpt \\
            --mcp-config ./docker-exec.json

    docker-exec.json example:
        {
          "mcpServers": {
            "docker": {
              "transport": "stdio",
              "command": "docker-exec-mcp",
              "args": ["--mount", "/home/user/ducktape:/workspace:ro"]
            }
          }
        }
    """
    # Load MCP config
    if mcp_config and mcp_config.exists():
        config = MCPConfig.model_validate_json(mcp_config.read_text())
    else:
        config = MCPConfig(mcpServers={})

    # Load initial policy
    policy_source = None
    if initial_policy and initial_policy.exists():
        policy_source = initial_policy.read_text()

    # Run async server
    asyncio.run(
        _run_server(
            agent_id=agent_id,
            db_path=db_path,
            mcp_config=config,
            host=host,
            port=port,
            initial_policy=policy_source,
        )
    )


async def _run_server(
    agent_id: str,
    db_path: Path,
    mcp_config: MCPConfig,
    host: str,
    port: int,
    initial_policy: str | None,
):
    """Run the HTTP MCP bridge server."""
    # Initialize persistence
    db_path.parent.mkdir(parents=True, exist_ok=True)
    persistence = SQLitePersistence(str(db_path))
    await persistence.__aenter__()

    # Initialize Docker client
    docker_client = docker.from_env()

    try:
        # Create infrastructure
        builder = MCPInfrastructure(
            agent_id=agent_id,
            persistence=persistence,
            docker_client=docker_client,
            initial_policy=initial_policy,
        )

        running = await builder.start(mcp_config)

        # Attach sidecars (none for external agents)
        bundle = SidecarBundle.for_external_agent()
        await bundle.attach_all(running)

        # TODO: Expose running.compositor over HTTP/SSE transport
        # The compositor is already a FastMCP server - we just need to serve it via HTTP
        #
        # Options:
        # 1. Use FastMCP's built-in HTTP transport (if available)
        # 2. Create FastAPI app with SSE endpoint that proxies to compositor
        # 3. Use mcp.server.sse.SseServerTransport
        #
        # For now, log and keep alive
        logger.info(f"HTTP MCP Bridge started for agent_id={agent_id}")
        logger.info(f"Compositor ready with {len(mcp_config.mcpServers)} external servers")
        logger.info(f"TODO: Expose compositor at http://{host}:{port}/mcp")

        # Keep alive
        await asyncio.Event().wait()

    finally:
        await running.close()
        await persistence.__aexit__(None, None, None)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    cli()
