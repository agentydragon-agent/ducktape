"""Shared CLI utilities for props commands."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import typer

from props.core.ids import SnapshotSlug
from props.core.models.examples import ExampleSpec, WholeSnapshotExample


def make_example_from_files(
    snapshot_slug: SnapshotSlug, all_files: Mapping[Path, object], requested_files: list[str] | None
) -> ExampleSpec:
    """Create an ExampleSpec from file filter. Only supports whole-snapshot for now."""
    # No filter → return WholeSnapshotExample
    if requested_files is None:
        return WholeSnapshotExample(snapshot_slug=snapshot_slug)

    # Per-file filtering requires database lookup to get/create trigger_set_id
    # This would require session access and trigger set creation
    # For now, CLI only supports whole-snapshot review
    typer.echo("Error: Per-file filtering is not yet supported in CLI", err=True)
    typer.echo("Use --files without arguments to review entire snapshot", err=True)
    raise typer.Exit(1)
