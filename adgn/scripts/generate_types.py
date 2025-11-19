#!/usr/bin/env python3
"""Generate TypeScript types from Pydantic models.

This script extracts Pydantic models from the agent package and generates
TypeScript interface definitions for use in the web UI.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

# Import models to export
from adgn.agent.approvals import ApprovalRequest
from adgn.agent.mcp_bridge.servers.agents import (
    AbortAgentArgs,
    AgentApprovalsHistory,
    AgentApprovalsPending,
    AgentInfo,
    AgentList,
    AgentPolicyProposals,
    ApprovalHistoryEntry,
    ApproveToolCallArgs,
    PendingApproval,
    PolicyProposalInfo,
    RejectToolCallArgs,
)
from adgn.agent.persist import (
    ApprovalOutcome,
    Decision,
    EventType,
    RunStatus,
    ToolCallExecution,
    ToolCallRecord,
)
from adgn.agent.types import ToolCall


def get_json_schema(model: type) -> dict[str, Any]:
    """Get JSON Schema for a Pydantic model."""
    adapter = TypeAdapter(model)
    return adapter.json_schema(mode="serialization")


def generate_typescript_from_schema(schema: dict[str, Any], type_name: str) -> str:
    """Generate TypeScript interface from JSON Schema using json-schema-to-typescript."""
    # Write schema to temporary file
    schema_json = json.dumps(schema, indent=2)

    # Call json-schema-to-typescript CLI
    try:
        result = subprocess.run(
            ["npx", "json-schema-to-typescript", "--stdin", "--bannerComment", ""],
            input=schema_json,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"Error generating TypeScript for {type_name}:", file=sys.stderr)
        print(e.stderr, file=sys.stderr)
        raise


def main() -> None:
    """Generate TypeScript types from Pydantic models."""
    # Define models to export (in desired order)
    # Name is derived from class __name__ - no duplication
    models_to_export = [
        # Core types
        ToolCall,
        # Enums
        ApprovalOutcome,
        RunStatus,
        EventType,
        # Decision and execution
        Decision,
        ToolCallExecution,
        ToolCallRecord,
        # Approval types
        ApprovalRequest,
        PendingApproval,
        ApprovalHistoryEntry,
        # Agent info
        AgentInfo,
        AgentList,
        AgentApprovalsPending,
        AgentApprovalsHistory,
        PolicyProposalInfo,
        AgentPolicyProposals,
        # Tool args
        ApproveToolCallArgs,
        RejectToolCallArgs,
        AbortAgentArgs,
    ]

    # Output directory
    project_root = Path(__file__).parent.parent
    output_dir = project_root / "src" / "adgn" / "agent" / "web" / "src" / "generated"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "types.ts"

    print(f"Generating TypeScript types to {output_file}...")

    # Collect all schemas and definitions
    # Python dicts remember iteration order, so no separate type_order needed
    all_defs: dict[str, Any] = {}

    # First pass: collect all schemas and their definitions
    for model_class in models_to_export:
        type_name = model_class.__name__
        print(f"  Processing {type_name}...")
        schema = get_json_schema(model_class)

        # Collect all definitions
        if "$defs" in schema:
            all_defs.update(schema["$defs"])

        # Store the main schema as a definition (order preserved by dict)
        main_schema = {k: v for k, v in schema.items() if k != "$defs"}
        all_defs[type_name] = main_schema

    # Create a unified schema with all definitions
    # We create a dummy root schema that references all our main types
    # Use all_defs keys directly (order preserved since Python 3.7+)
    unified_schema = {
        "type": "object",
        "title": "AgentTypes",
        "properties": {name: {"$ref": f"#/$defs/{name}"} for name in all_defs.keys() if name in [m.__name__ for m in models_to_export]},
        "$defs": all_defs,
    }

    # Generate TypeScript from the unified schema
    try:
        ts_code = generate_typescript_from_schema(unified_schema, "AgentTypes")
        # Clean up and write output
        ts_output = []
        ts_output.append("// Auto-generated TypeScript types from Pydantic models")
        ts_output.append("// Do not edit manually - regenerate with: npm run generate-types")
        ts_output.append("")
        ts_output.append(ts_code.strip())

        output_file.write_text("\n".join(ts_output))
        print(f"✓ Successfully generated TypeScript types for {len(models_to_export)} models")
    except Exception as e:
        print(f"Error generating TypeScript: {e}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
