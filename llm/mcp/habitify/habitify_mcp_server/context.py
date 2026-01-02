"""Server context for Habitify MCP server."""

from contextlib import asynccontextmanager
from dataclasses import dataclass

from mcp.server.fastmcp import FastMCP

from .config import load_api_key
from .habitify_client import HabitifyClient


@dataclass
class HabitifyContext:
    """Server context holding the Habitify API client."""

    client: HabitifyClient


@asynccontextmanager
async def lifespan(server: FastMCP):
    """Initialize client once at server startup, share across all requests."""
    api_key = load_api_key(exit_on_missing=False)
    if not api_key:
        raise RuntimeError(
            "HABITIFY_API_KEY environment variable is required. "
            "Set it in .env or pass via --api-key."
        )
    async with HabitifyClient(api_key=api_key) as client:
        yield HabitifyContext(client=client)
