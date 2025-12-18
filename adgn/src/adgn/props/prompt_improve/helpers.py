"""Helper functions for the improvement agent.

These helpers simplify the improvement workflow by providing typed interfaces
for submitting improved prompts via MCP-over-HTTP.

Typical workflow:
    1. Register improvement run (before temp user creation)
    2. Write improved prompt to /workspace/{filename}
    3. Call submit_prompt() to submit it via MCP
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from adgn.props.agent_helpers import mcp_client_from_env
from adgn.props.db.models import ImprovementRun
from adgn.props.ids import SnapshotSlug


async def register_improvement_run(
    conn: AsyncConnection, run_id: UUID, allowed_examples: list[tuple[SnapshotSlug, str]]
) -> None:
    """Register an improvement run with its allowed examples.

    Must be called BEFORE creating the temp user, so the RLS policies
    can look up the allowed examples.

    The run is stored in the improvement_runs table with:
    - id: The run_id (same as temp user username suffix)
    - allowed_examples: JSONB array of {snapshot_slug, scope_hash} objects
    - status: 'in_progress' (default)

    Args:
        conn: Async database connection (admin-privileged)
        run_id: UUID of the improvement run
        allowed_examples: List of (snapshot_slug, scope_hash) tuples
    """
    examples_json = [{"snapshot_slug": slug, "scope_hash": hash_} for slug, hash_ in allowed_examples]
    stmt = insert(ImprovementRun).values(id=run_id, allowed_examples=examples_json)
    await conn.execute(stmt)


async def submit_prompt(prompt_file: str, rationale: str, expected_improvement: str) -> None:
    """Submit an improved prompt via MCP.

    Calls the submit_prompt tool on the prompt_submission server to submit
    the improved prompt for evaluation.

    Args:
        prompt_file: Basename of prompt file in /workspace/ (e.g., 'improved-prompt.md')
        rationale: Explanation of what you changed and why (2-5 sentences)
        expected_improvement: What failure patterns this should fix

    Raises:
        ToolError: If the MCP call fails (raised automatically by fastmcp)

    Example:
        import asyncio
        from adgn.props.prompt_improve.helpers import submit_prompt

        # First write the prompt file (via docker_exec)
        # Then submit it:
        asyncio.run(submit_prompt(
            prompt_file="improved-prompt.md",
            rationale="Added explicit dead code detection step with AST analysis",
            expected_improvement="Better detection of unused imports and unreachable code"
        ))

    Note:
        This function is async and must be called with asyncio.run() or await.
        The prompt file must exist in the workspace before calling this function.
    """
    async with mcp_client_from_env() as (client, _init_result):
        # raise_on_error=True (default) raises ToolError on failure
        await client.call_tool(
            "submit_prompt",
            {"prompt_file": prompt_file, "rationale": rationale, "expected_improvement": expected_improvement},
        )
