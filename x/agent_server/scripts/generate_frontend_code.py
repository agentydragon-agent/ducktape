"""Generate TypeScript code from Python sources.

Two code generation tasks:
1. MCP resource URI constants → mcpConstants.ts (--constants-output)
2. Pydantic model schemas → types.ts (--types-output, requires --jst-binary)

Intended to be run as a Bazel genrule tool:
  generate_frontend_code --constants-output $@ [--types-output $@ --jst-binary <path>]
"""

from __future__ import annotations

import argparse
import inspect
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

import x.agent_server.web_api_constants as _web_constants
from agent_core.events import ToolCall
from x.agent_server.approvals import ApprovalRequest
from x.agent_server.mcp_bridge.agents import AgentInfo
from x.agent_server.persist.types import ApprovalOutcome, EventType
from x.agent_server.server.protocol import AgentStatus

# ============================================================================
# MCP Constants Generation
# ============================================================================


def extract_uri_constants() -> dict[str, str]:
    """Extract Final[str] URI constants from the web_api_constants module."""
    constants: dict[str, str] = {}
    for name, value in inspect.getmembers(_web_constants):
        if isinstance(value, str) and "URI" in name and not name.startswith("_"):
            constants[name] = value
    return constants


def classify_constants(constants: dict[str, str]) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Classify constants into simple URIs and format strings."""
    simple_uris: list[tuple[str, str]] = []
    format_uris: list[tuple[str, str]] = []
    for name, value in sorted(constants.items()):
        if "{" in value and "}" in value:
            format_uris.append((name, value))
        else:
            simple_uris.append((name, value))
    return simple_uris, format_uris


def _to_camel_case(snake_str: str) -> str:
    """Convert UPPER_SNAKE_CASE to camelCase."""
    components = snake_str.split("_")
    return components[0].lower() + "".join(x.capitalize() for x in components[1:])


def _extract_format_params(format_str: str) -> list[str]:
    """Extract parameter names from a format string like 'resource://foo/{bar}'."""
    matches = re.findall(r"\{(\w+)\}", format_str)
    return list(dict.fromkeys(matches))


def _escape_format_string(format_str: str) -> str:
    """Escape a format string for use in TypeScript template literals."""
    return re.sub(r"\{(\w+)\}", r"${\1}", format_str)


def generate_mcp_constants_typescript(simple_uris: list[tuple[str, str]], format_uris: list[tuple[str, str]]) -> str:
    output: list[str] = ["// Auto-generated MCP resource URI constants — do not edit manually", ""]
    if simple_uris:
        output.append("/** Simple resource URI constants */")
        output.append("export const MCPUris = {")
        for py_name, uri in simple_uris:
            ts_name = _to_camel_case(py_name)
            output.append(f"  {ts_name}: '{uri}',")
        output.append("} as const")
        output.append("")
    if format_uris:
        output.append("/** Helper functions for parameterised resource URIs */")
        for py_name, format_str in format_uris:
            ts_func_name = _to_camel_case(py_name.replace("_FMT", ""))
            params = _extract_format_params(format_str)
            if params:
                param_defs = ", ".join(f"{p}: string" for p in params)
                output.append(f"export function {ts_func_name}({param_defs}): string {{")
                output.append(f"  return `{_escape_format_string(format_str)}`")
                output.append("}")
            else:
                ts_name = _to_camel_case(py_name)
                output.append(f"export const {ts_name} = '{format_str}' as const")
        output.append("")
    return "\n".join(output)


def generate_constants(output_path: Path) -> None:
    constants = extract_uri_constants()
    if not constants:
        print("Warning: no URI constants found", file=sys.stderr)
    simple_uris, format_uris = classify_constants(constants)
    ts_code = generate_mcp_constants_typescript(simple_uris, format_uris)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(ts_code)


# ============================================================================
# TypeScript Types Generation
# ============================================================================


def _build_unified_schema() -> dict[str, Any]:
    models_to_export = [ToolCall, ApprovalOutcome, AgentStatus, EventType, ApprovalRequest, AgentInfo]
    all_defs: dict[str, Any] = {}
    for model_class in models_to_export:
        schema = TypeAdapter(model_class).json_schema(mode="serialization")
        if "$defs" in schema:
            all_defs.update(schema["$defs"])
        all_defs[model_class.__name__] = {k: v for k, v in schema.items() if k != "$defs"}
    return {
        "type": "object",
        "title": "AgentTypes",
        "properties": {
            name: {"$ref": f"#/$defs/{name}"} for name in all_defs if name in {m.__name__ for m in models_to_export}
        },
        "$defs": all_defs,
    }


def generate_types(output_path: Path, jst_binary: Path) -> None:
    unified_schema = _build_unified_schema()
    schema_json = json.dumps(unified_schema, indent=2)
    result = subprocess.run(
        [str(jst_binary), "--stdin", "--bannerComment", ""],
        input=schema_json,
        capture_output=True,
        text=True,
        check=True,
    )
    ts_output = "\n".join(
        [
            "// Auto-generated TypeScript types from Pydantic models — do not edit manually",
            "",
            result.stdout.strip(),
            "",
        ]
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(ts_output)


# ============================================================================
# Main
# ============================================================================


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate TypeScript from Python sources")
    parser.add_argument("--constants-output", type=Path, help="Output path for mcpConstants.ts")
    parser.add_argument("--types-output", type=Path, help="Output path for types.ts")
    parser.add_argument("--jst-binary", type=Path, help="Path to json-schema-to-typescript binary (json2ts)")
    args = parser.parse_args()

    if not args.constants_output and not args.types_output:
        parser.error("At least one of --constants-output or --types-output is required")

    if args.constants_output:
        generate_constants(args.constants_output)

    if args.types_output:
        if not args.jst_binary:
            parser.error("--jst-binary is required when --types-output is specified")
        generate_types(args.types_output, args.jst_binary)


if __name__ == "__main__":
    main()
