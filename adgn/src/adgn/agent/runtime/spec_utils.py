from __future__ import annotations

from typing import Any

from pydantic import TypeAdapter

from .specs import McpServerSpec


def rehydrate_mcp_specs(specs_json: dict[str, Any] | None) -> dict[str, McpServerSpec]:
    """Convert persisted JSON specs into typed McpServerSpec mapping.

    - Returns an empty dict if specs_json is falsy.
    - Raises on validation errors (does not silently skip bad entries).
    """
    out: dict[str, McpServerSpec] = {}
    if not specs_json:
        return out
    spec_ta: TypeAdapter[McpServerSpec] = TypeAdapter(McpServerSpec)
    for name, spec_json in specs_json.items():
        out[name] = spec_ta.validate_python(spec_json)
    return out
