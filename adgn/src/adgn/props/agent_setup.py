"""Shared utilities for setting up agent workflows in props evaluation."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from adgn.agent.db_event_handler import DatabaseEventHandler
from adgn.agent.display import CompactDisplayHandler
from adgn.agent.handler import BaseHandler
from adgn.props.cli.common_options import DEFAULT_MAX_LINES

if TYPE_CHECKING:
    from adgn.mcp.compositor.server import Compositor

logger = logging.getLogger(__name__)


async def build_props_handlers(
    *, transcript_id: UUID, verbose_prefix: str | None, compositor: Compositor, max_lines: int = DEFAULT_MAX_LINES
) -> list[BaseHandler]:
    """Build standard handlers for props agent workflows.

    # TODO: Refactor display config threading. Currently `verbose` and `max_lines` are passed
    # separately from CLI through run_critic/run_grader, while `verbose_prefix` is constructed
    # mid-way from internal context (transcript_id, snapshot_slug, etc.). Consider consolidating
    # into a single `DisplayConfig | None` param constructed at the same level as the prefix,
    # with CLI just passing `max_lines: int | None` (None = no display).

    Always includes DatabaseEventHandler for transcript persistence.
    Conditionally includes CompactDisplayHandler if verbose_prefix is provided.

    Args:
        transcript_id: Transcript ID for database event tracking
        verbose_prefix: Optional prefix for verbose display (e.g., "[CRITIC snapshot-slug] ").
                       If None, no verbose handler is added.
        compositor: Compositor instance for extracting server schemas
        max_lines: Max lines per event in verbose display (default from common_options)
    """
    handlers: list[BaseHandler] = [DatabaseEventHandler(transcript_id=transcript_id)]

    if verbose_prefix is not None:
        display_handler = await CompactDisplayHandler.from_compositor(
            compositor, max_lines=max_lines, prefix=verbose_prefix
        )
        handlers.append(display_handler)

    return handlers
