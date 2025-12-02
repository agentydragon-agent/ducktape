"""Shared CLI option constants for adgn-properties commands."""

from __future__ import annotations

import typer

# Options - General
OPT_MODEL = typer.Option("gpt-5", help="Model id")
OPT_VERBOSE = typer.Option(False, "--verbose", "-v", help="Enable verbose output")

# Options - Specimen & Files
OPT_SPECIMEN = typer.Option(None, "--specimen", help="Specimen slug")
OPT_FILES_FILTER = typer.Option(None, "--files", help="Limit review to specific files (relative paths)")
