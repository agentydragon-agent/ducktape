"""Habitify MCP Server implementation."""

import os
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from . import tools
from .context import lifespan
from .habitify_client import HabitifyClient
from .types import Status


def create_habitify_mcp_server(
    debug: bool = False, log_level: str = "INFO", api_key: str | None = None, port: int = 3000
) -> FastMCP:
    """Create and configure a Habitify MCP server."""
    # Set API key in environment if provided (for lifespan to pick up)
    if api_key:
        os.environ["HABITIFY_API_KEY"] = api_key

    server = FastMCP(
        "Habitify",
        description="Habitify API for habit tracking through Model Context Protocol",
        dependencies=["httpx", "python-dotenv"],
        debug=debug,
        log_level=log_level,
        port=port,
        lifespan=lifespan,
    )

    def get_client(ctx: Context) -> HabitifyClient:
        """Get the HabitifyClient from the lifespan context."""
        return ctx.request_context.lifespan_context

    @server.tool()
    async def get_habits(ctx: Context, include_archived: bool = False) -> dict[str, Any]:
        return await tools.get_habits(get_client(ctx), include_archived=include_archived)

    @server.tool()
    async def get_habit(ctx: Context, id: str | None = None, name: str | None = None) -> dict[str, Any]:
        return await tools.get_habit(get_client(ctx), id=id, name=name)

    @server.tool()
    async def get_habit_status(
        ctx: Context,
        id: str | None = None,
        name: str | None = None,
        date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        days: int | None = None,
    ) -> dict[str, Any]:
        """Get habit status for single date or date range.

        Single date: use 'date' (YYYY-MM-DD, defaults to today)

        Date range (inclusive): use one of:
        - start_date + end_date: specific range
        - start_date + days: N days from start
        - end_date + days: N days before end
        - days: N days ending today
        """
        return await tools.get_habit_status(
            get_client(ctx), id=id, name=name, date=date, start_date=start_date, end_date=end_date, days=days
        )

    @server.tool()
    async def set_habit_status(
        ctx: Context,
        id: str | None = None,
        name: str | None = None,
        status: Status = Status.COMPLETED,
        date: str | None = None,
        note: str | None = None,
        value: float | None = None,
    ) -> dict[str, Any]:
        return await tools.set_habit_status(
            get_client(ctx), id=id, name=name, status=status, date=date, note=note, value=value
        )

    return server
