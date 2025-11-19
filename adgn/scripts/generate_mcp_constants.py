#!/usr/bin/env python3
"""Generate TypeScript constants from Python MCP resource URI constants.

This script extracts MCP resource URI patterns from Python constants and
generates TypeScript helper functions to avoid hardcoded strings in the frontend.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from typing import Any


def extract_constants_from_file(python_file: Path) -> dict[str, Any]:
    """Extract Final[str] constants from a Python file using runtime evaluation."""
    # Read and execute the file to get the actual values
    # This handles f-strings and other dynamic expressions correctly
    namespace: dict[str, Any] = {}

    try:
        with open(python_file) as f:
            code = f.read()
        # Execute the file in an isolated namespace
        exec(code, namespace)
    except Exception as e:
        print(f"Error executing constants file: {e}", file=sys.stderr)
        raise

    constants: dict[str, Any] = {}

    # Extract all string constants that contain 'URI'
    for name, value in namespace.items():
        if isinstance(value, str) and "URI" in name and not name.startswith("_"):
            constants[name] = value

    return constants


def classify_constants(
    constants: dict[str, Any],
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Classify constants into simple URIs and format strings."""
    simple_uris: list[tuple[str, str]] = []
    format_uris: list[tuple[str, str]] = []

    for name, value in sorted(constants.items()):
        if isinstance(value, str):
            if "{" in value and "}" in value:
                format_uris.append((name, value))
            else:
                simple_uris.append((name, value))

    return simple_uris, format_uris


def generate_typescript(
    simple_uris: list[tuple[str, str]], format_uris: list[tuple[str, str]]
) -> str:
    """Generate TypeScript constants and helpers."""
    output: list[str] = []

    output.append("// Auto-generated MCP resource URI constants")
    output.append("// Do not edit manually - regenerate with: npm run generate-mcp-constants")
    output.append("")

    # Simple URI constants
    if simple_uris:
        output.append("/** Simple resource URI constants */")
        output.append("export const MCPUris = {")
        for py_name, uri in simple_uris:
            # Convert snake_case to camelCase for TS
            ts_name = _to_camel_case(py_name)
            output.append(f"  {ts_name}: '{uri}',")
        output.append("} as const")
        output.append("")

    # Helper functions for format strings
    if format_uris:
        output.append("/** Helper functions for resource URI format strings */")
        for py_name, format_str in format_uris:
            ts_func_name = _to_camel_case(py_name.replace("_FMT", ""))
            params = _extract_format_params(format_str)

            if params:
                # Generate a typed function
                param_defs = ", ".join([f"{p}: string" for p in params])
                output.append(f"export function {ts_func_name}({param_defs}): string {{")
                output.append(f"  return `{_escape_format_string(format_str)}`")
                output.append("}")
            else:
                # Just a constant
                ts_name = _to_camel_case(py_name)
                output.append(f"export const {ts_name} = '{format_str}' as const")

        output.append("")

    return "\n".join(output)


def _to_camel_case(snake_str: str) -> str:
    """Convert UPPER_SNAKE_CASE to camelCase."""
    components = snake_str.split("_")
    # Keep the first component lowercase, capitalize the rest
    return components[0].lower() + "".join(x.capitalize() for x in components[1:])


def _extract_format_params(format_str: str) -> list[str]:
    """Extract parameter names from a format string like 'resource://foo/{bar}'."""
    matches = re.findall(r"\{(\w+)\}", format_str)
    return list(dict.fromkeys(matches))  # Remove duplicates while preserving order


def _escape_format_string(format_str: str) -> str:
    """Escape a format string for use in template literals."""
    # Replace {param} with ${param} for JavaScript template literals
    return re.sub(r"\{(\w+)\}", r"${\1}", format_str)


def main() -> None:
    """Generate TypeScript MCP constants from Python."""
    # Path to the Python constants file
    project_root = Path(__file__).parent.parent
    constants_file = (
        project_root
        / "src"
        / "adgn"
        / "mcp"
        / "_shared"
        / "constants.py"
    )

    if not constants_file.exists():
        print(f"Error: Constants file not found at {constants_file}", file=sys.stderr)
        sys.exit(1)

    # Output directory
    output_dir = (
        project_root
        / "src"
        / "adgn"
        / "agent"
        / "web"
        / "src"
        / "generated"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "mcpConstants.ts"

    print(f"Generating TypeScript MCP constants from {constants_file}...")

    # Extract constants from Python file
    constants = extract_constants_from_file(constants_file)

    if not constants:
        print("Warning: No URI constants found in Python file", file=sys.stderr)
        return

    print(f"  Found {len(constants)} URI constants")

    # Classify constants
    simple_uris, format_uris = classify_constants(constants)

    print(f"  Simple URIs: {len(simple_uris)}")
    print(f"  Format strings: {len(format_uris)}")

    # Generate TypeScript
    ts_code = generate_typescript(simple_uris, format_uris)

    # Write output
    output_file.write_text(ts_code)
    print(f"✓ Successfully generated TypeScript MCP constants to {output_file}")


if __name__ == "__main__":
    main()
