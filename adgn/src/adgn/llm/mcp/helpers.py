"""MCP helper utilities for creating model-facing function-call payloads.

This module provides a small, ergonomic helper for tests and bootstraps to
produce OpenAI/Responses-style function-call objects that use the canonical
MCP namespaced tool format ("mcp__{server}__{tool}").

Keep this tiny helper so bootstraps can emit exactly what the model would.
"""

from __future__ import annotations

import json
from typing import Any
import uuid

from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseInputMessageItem,
    ResponseInputTextParam,
)

from adgn.llm.mini_codex.mcp_manager import build_mcp_function


def make_openai_function_call_full(
    server: str,
    tool: str,
    arguments: dict[str, Any],
    *,
    as_json: bool = False,
) -> dict[str, Any]:
    """Return a full function-call payload including a generated call_id and timestamp.

    The returned dict matches the top-level event payload shape used in our
    recordings and examples, e.g.:

    {
        "name": "mcp__server__tool",
        "type": "function_call",
        "call_id": "call_<uuid>",
        "arguments": {...} or JSON string,
    }

    Args:
        server: MCP server name (e.g. "editor").
        tool: tool name under the server (e.g. "read_file").
        arguments: dict of arguments.
        as_json: serialize arguments into a JSON string when True.

    Returns:
        dict with keys: name, type, call_id, arguments
    """
    name = build_mcp_function(server, tool)
    cid = f"call_{uuid.uuid4().hex}"
    args = json.dumps(arguments) if as_json else arguments
    return {
        "name": name,
        "type": "function_call",
        "call_id": cid,
        "arguments": args,
    }


def make_response_function_tool_call_full(
    server: str,
    tool: str,
    arguments: dict[str, Any],
    *,
    as_json: bool = False,
) -> ResponseFunctionToolCall:
    """Return an OpenAI SDK ResponseFunctionToolCall populated from the
    canonical MCP namespaced tool and arguments. The 'arguments' field is
    serialized to JSON (the SDK's ResponseFunctionToolCall expects a JSON string
    in many test fixtures), and a stable call_id is generated.
    """
    ev = make_openai_function_call_full(server, tool, arguments, as_json=as_json)
    # ResponseFunctionToolCall fields: type, name, arguments, call_id
    return ResponseFunctionToolCall(
        type=ev.get("type"),
        name=ev.get("name"),
        arguments=ev.get("arguments"),
        call_id=ev.get("call_id"),
    )


def make_response_input_user_text(
    text: str, *, id: str | None = None
) -> ResponseInputMessageItem:
    """Factory for a typed user input_text message for Responses API.

    Provides required fields (id, type, role) and wraps 'text' as an input_text content item.
    """
    return ResponseInputMessageItem(
        id=id or f"msg_{uuid.uuid4().hex}",
        type="message",
        role="user",
        content=[ResponseInputTextParam(type="input_text", text=text)],
    )


def make_response_input_function_call(
    *, name: str, call_id: str, arguments: dict[str, Any] | str
) -> ResponseFunctionToolCall:
    """Factory for a typed function_call input item (OpenAI SDK object)."""
    args_str = json.dumps(arguments) if isinstance(arguments, dict) else str(arguments)
    return ResponseFunctionToolCall(
        type="function_call", name=name, call_id=call_id, arguments=args_str
    )


def make_response_input_function_call_output(
    *, call_id: str, output: str
) -> dict[str, Any]:
    """Factory for function_call_output input item (dict shape per Responses API)."""
    return {"type": "function_call_output", "call_id": call_id, "output": output}
