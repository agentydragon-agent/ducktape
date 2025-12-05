"""HTTP-exposed grader submit MCP server.

Wraps the existing grader submit functionality with HTTP transport
and bearer token authentication for use by Docker-isolated agents.
"""

from __future__ import annotations

import logging

from fastmcp.server.auth import StaticTokenVerifier

from adgn.mcp.notifying_fastmcp import NotifyingFastMCP
from adgn.props.grader.grader import GradeInputs, GradeSubmitState, build_grader_submit_tools

logger = logging.getLogger(__name__)

# Server instructions exposed via MCP initialize()
GRADER_SUBMIT_INSTRUCTIONS = """\
Grader submission server for critique evaluation.

This server provides a single tool for submitting grading results:

## submit_result

Submit the final grading result comparing critique against ground truth.

The tool accepts a GradeSubmitInput payload containing:
- canonical_tp_coverage: Coverage of canonical true positives by critique issues
- canonical_fp_coverage: Coverage of known false positives by critique issues
- novel_critique_issues: Reasoning for novel issues not in ground truth
- reported_issue_ratios: TP/FP/unlabeled ratios across reported issues
- recall: Weighted fraction of canonical TPs covered
- summary: Markdown rationale for the grading

Call list_tools() to see the full input schema with field descriptions.
"""


def create_grader_submit_http_server(
    token: str,
    *,
    state: GradeSubmitState,
    inputs: GradeInputs,
    name: str = "grader_submit",
) -> NotifyingFastMCP:
    """Create HTTP-exposed grader submit MCP server with auth configured.

    Args:
        token: Bearer token for authentication.
        state: State container for submitted result.
        inputs: Grading context (snapshot slug and critique).
        name: Server name (default: grader_submit).

    Returns:
        FastMCP server ready to serve via http_app().
    """
    # Configure auth with static token
    # The token dict maps token string -> claims dict
    # We use a simple "agent" client_id with no specific scopes
    auth = StaticTokenVerifier(
        tokens={token: {"client_id": "grader-agent", "scopes": []}},
    )

    # Create server with auth and instructions
    server = NotifyingFastMCP(
        name,
        instructions=GRADER_SUBMIT_INSTRUCTIONS,
        auth=auth,
    )

    # Register the submit tool
    build_grader_submit_tools(server, state, inputs=inputs)

    logger.info(f"Created grader submit HTTP server '{name}' with auth")
    return server
