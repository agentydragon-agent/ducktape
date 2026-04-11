"""Parse raw tool_input dicts into typed Pydantic models.

Raises on parse failure — callers catch and surface to mailbox.
Returns None for unknown tools (no model registered).
"""

import logging
from typing import Any

from devinfra.claude.claude_api.tool_input_models import TOOL_INPUT_MAP, _ToolInputBase

logger = logging.getLogger(__name__)


def parse_tool_input(tool_name: str, tool_input: dict[str, Any]) -> _ToolInputBase | None:
    """Parse tool_input into a typed model. Returns None for unknown tools. Raises on parse failure."""
    model_class = TOOL_INPUT_MAP.get(tool_name)
    if model_class is None:
        return None
    return model_class.model_validate(tool_input)
