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

from adgn.agent.mcp_bridge.server import create_bridge_infrastructure
from adgn.agent.persist.sqlite import SQLitePersistence

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
    """Start HTTP MCP Bridge server."""
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
    import uvicorn

    # Initialize persistence
    db_path.parent.mkdir(parents=True, exist_ok=True)
    persistence = SQLitePersistence(str(db_path))

    # Initialize Docker client
    docker_client = docker.from_env()

    async with persistence:
        running = await create_bridge_infrastructure(
            agent_id=agent_id,
            persistence=persistence,
            docker_client=docker_client,
            mcp_config=mcp_config,
            initial_policy=initial_policy,
        )

        async with running:
            app = running.compositor.http_app()

            logger.info(f"HTTP MCP Bridge started for agent_id={agent_id}")
            logger.info(f"Compositor ready with {len(mcp_config.mcpServers or {})} external servers")
            logger.info(f"MCP server available at http://{host}:{port}/mcp")

            config = uvicorn.Config(
                app=app,
                host=host,
                port=port,
                log_level="info",
            )
            server = uvicorn.Server(config)
            await server.serve()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    cli()
