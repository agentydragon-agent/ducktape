"""Shared CLI option constants for props commands."""

from __future__ import annotations

import typer

# Options - Model Selection
OPT_OPTIMIZER_MODEL = typer.Option("gpt-5.1", help="Model for critic developer agent")
OPT_CRITIC_MODEL = typer.Option("gpt-5.1-codex-mini", help="Model for critic execution")
OPT_GRADER_MODEL = typer.Option("gpt-5.1-mini", help="Model for grader execution")
