"""Shared CLI option constants for adgn-properties commands."""

from __future__ import annotations

import typer

from adgn.props.cli_app.types import SNAPSHOT_SLUG
from adgn.props.docker_env import WORKING_DIR as CRITIC_WORKDIR

# Arguments
ARG_WORKDIR = typer.Argument(..., exists=True, file_okay=False, resolve_path=True)
ARG_SCOPE = typer.Argument(..., help="Freeform scope description (e.g. 'all files under src/**')")
ARG_SNAPSHOT = typer.Argument(..., help="Snapshot slug (under properties/specimens)", click_type=SNAPSHOT_SLUG)
ARG_ISSUE_ID = typer.Argument(..., help="Issue id to lint (must have should_flag=true)")
ARG_OCCURRENCE = typer.Argument(..., help="0-based occurrence index")
ARG_CMD_LIST = typer.Argument(..., help="Command to run inside container")
ARG_PROMPT = typer.Argument(..., help="Candidate critic system prompt to evaluate across snapshots")

# Options - General
OPT_MODEL = typer.Option("gpt-5", help="Model id")
OPT_DRY_RUN = typer.Option(False, help="Compose prompt only; do not run")
OPT_FINAL_ONLY = typer.Option(False, help="Print only final message")
OPT_OUTPUT_FINAL_MESSAGE = typer.Option(None, help="Write final message to this path")
OPT_ALLOW_GENERAL = typer.Option(False, help="Allow general code-quality findings beyond formal properties")
OPT_OUTPUT_DIR = typer.Option(None, help="Root directory for run artifacts")
OPT_MAX_ITERS = typer.Option(10, help="Maximum number of prompt evaluations (tool calls)")
OPT_VERBOSE = typer.Option(False, "--verbose", "-v", help="Enable verbose output")

# Options - Context & Environment
OPT_CONTEXT = typer.Option(
    "minimal", help=("Agent context: minimal (no extra servers) or props (mount /props via docker MCP)")
)
OPT_WORKDIR_CRITIC = typer.Option(CRITIC_WORKDIR, "--workdir", help="Container working dir (default: /workspace)")

# Options - Snapshot & Files
OPT_SNAPSHOT = typer.Option(None, "--snapshot", help="Snapshot slug")
OPT_FILES_FILTER = typer.Option(None, "--files", help="Limit review to specific files (relative paths)")

# Options - Grading & Critique
OPT_CRITIQUE = typer.Option(..., "--critique", exists=True, help="Path to the input critique JSON file")

# Options - Docker Execution
OPT_INTERACTIVE = typer.Option(False, "-i", help="Attach STDIN (docker exec -i)")
OPT_TTY_EXEC = typer.Option(False, "-t", help="Allocate TTY (docker exec -t)")
OPT_SKIP_GIT_REPO_CHECK = typer.Option(False, help="Pass --skip-git-repo-check to codex exec")
OPT_FULL_AUTO = typer.Option(False, help="Pass --full-auto to codex exec")

# Options - Runbook/Path Selection
OPT_RUNBOOK_PATH = typer.Option(
    None,
    "--path",
    exists=True,
    file_okay=False,
    resolve_path=True,
    help="Local code path to mount as /workspace (read-only)",
)
OPT_RUNBOOK_SNAPSHOT = typer.Option(
    None, "--snapshot", help="Snapshot slug to hydrate and mount as /workspace (read-only)", click_type=SNAPSHOT_SLUG
)
