"""MCP helper utilities for creating model-facing function-call payloads.

This module provides a small, ergonomic helper for tests and bootstraps to
produce OpenAI/Responses-style function-call objects that use the canonical
MCP namespaced tool format ("mcp__{server}__{tool}").

Keep this tiny helper so bootstraps can emit exactly what the model would.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from adgn_llm.mini_codex.mcp_manager import build_mcp_function
import uuid
from datetime import datetime, timezone


def make_openai_function_call_full(
    server: str,
    tool: str,
    arguments: dict[str, Any],
    *,
    as_json: bool = False,
) -> Dict[str, Any]:
    """Return a full function-call payload including a generated call_id and timestamp.

    The returned dict matches the top-level event payload shape used in our
    recordings and examples, e.g.:

    {
        "name": "mcp__server__tool",
        "type": "function_call",
        "call_id": "call_<uuid>",
        "arguments": {...} or JSON string,
        "ts": "2025-09-15T12:34:56.789Z",
    }

    Args:
        server: MCP server name (e.g. "editor").
        tool: tool name under the server (e.g. "read_file").
        arguments: dict of arguments.
        as_json: serialize arguments into a JSON string when True.

    Returns:
        dict with keys: name, type, call_id, arguments, ts
    """
    name = build_mcp_function(server, tool)
    cid = f"call_{uuid.uuid4().hex}"
    args = json.dumps(arguments) if as_json else arguments
    ts = datetime.now(timezone.utc).isoformat()
    return {
        "name": name,
        "type": "function_call",
        "call_id": cid,
        "arguments": args,
        "ts": ts,
    }
