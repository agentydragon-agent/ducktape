"""Improvement agent CLI helper commands.

Provides CLI access to improvement helper functions for debugging and manual testing.

Usage:
    adgn-properties agent-helper improvement submit-prompt "improved-prompt.md" "Added explicit dead code detection" "Better detection of unused imports"
"""

from __future__ import annotations

import typer

from adgn.cli_utils import async_run
from adgn.props.prompt_improve.helpers import submit_prompt

app = typer.Typer(help="Improvement agent helper commands")


@app.command("submit-prompt")
@async_run
async def improvement_submit_prompt(
    prompt_file: str = typer.Argument(..., help="Basename of prompt file in /workspace/ (e.g., 'improved-prompt.md')"),
    rationale: str = typer.Argument(..., help="Explanation of what you changed and why (2-5 sentences)"),
    expected_improvement: str = typer.Argument(..., help="What failure patterns this should fix"),
) -> None:
    """Submit an improved prompt from a file in the workspace.

    The file should be written to /workspace/{prompt_file} before calling this command.
    This command calls the MCP submit_prompt tool via HTTP.

    Example:
        adgn-properties agent-helper improvement submit-prompt \\
            "improved-prompt.md" \\
            "Added explicit dead code detection step with AST analysis" \\
            "Better detection of unused imports and unreachable code"
    """
    await submit_prompt(prompt_file=prompt_file, rationale=rationale, expected_improvement=expected_improvement)
    typer.echo(f"Prompt submitted successfully from {prompt_file}")
