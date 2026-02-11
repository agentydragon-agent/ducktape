"""Shared utilities for setting up agent workflows in props evaluation."""

from __future__ import annotations

import logging
from uuid import UUID

from adgn.agent.db_event_handler import DatabaseEventHandler
from adgn.agent.handler import BaseHandler
from adgn.agent.rich_display import CompactDisplayHandler

logger = logging.getLogger(__name__)


def build_props_handlers(*, transcript_id: UUID, verbose_prefix: str | None, servers: dict) -> list[BaseHandler]:
    """Build standard handlers for props agent workflows.

    Always includes DatabaseEventHandler for transcript persistence.
    Conditionally includes RichDisplayHandler if verbose_prefix is provided.

    Args:
        transcript_id: Transcript ID for database event tracking
        verbose_prefix: Optional prefix for verbose display (e.g., "[CRITIC specimen-slug] ").
                       If None, no verbose handler is added.
        servers: Server dict for RichDisplayHandler (maps server names to FastMCP instances)
    """
    handlers: list[BaseHandler] = [DatabaseEventHandler(transcript_id=transcript_id)]

    if verbose_prefix is not None:
        # handlers.append(RichDisplayHandler(max_lines=10, prefix=verbose_prefix, servers=servers))
        handlers.append(CompactDisplayHandler(max_lines=10, prefix=verbose_prefix, servers=servers))

    return handlers
