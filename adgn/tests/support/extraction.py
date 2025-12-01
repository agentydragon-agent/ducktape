"""Extraction helpers for test assertions - parse structured content from MCP tool results."""

from __future__ import annotations

import json
import logging

from mcp import types as mcp_types
from pydantic import BaseModel, TypeAdapter

from adgn.mcp._shared.calltool import extract_structured_content
from adgn.openai_utils.model import FunctionCallOutputItem, ResponsesRequest

logger = logging.getLogger(__name__)


def get_last_function_output[T: BaseModel](req: ResponsesRequest, output_type: type[T]) -> T:
    """Extract and parse structured content from last FunctionCallOutputItem in request input.

    Args:
        req: ResponsesRequest containing function call outputs
        output_type: Pydantic model class to validate structured content as

    Returns:
        Parsed and validated instance of output_type

    Raises:
        RuntimeError: If no FunctionCallOutputItem found or item has no output
        ValueError: If structured content is missing or result is an error
    """
    if isinstance(req.input, str):
        raise RuntimeError("Cannot extract from string input")

    # Find last FunctionCallOutputItem with output
    for item in reversed(req.input):
        if isinstance(item, FunctionCallOutputItem):
            if not item.output:
                raise RuntimeError(f"FunctionCallOutputItem has no output: {item}")

            # Parse JSON to CallToolResult, then extract structured content
            result_dict = json.loads(item.output)
            result = TypeAdapter(mcp_types.CallToolResult).validate_python(result_dict)
            return extract_structured_content(result, output_type)

    raise RuntimeError(f"No FunctionCallOutputItem found in request input for {output_type.__name__}")
