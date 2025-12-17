"""Example: Query training examples for testing prompts.

This script demonstrates how to list training examples (snapshot_slug, scope_hash pairs)
that can be passed to run_critic_on_example.
"""

from typing import Any

from rich.console import Console

from adgn.props.agent_helpers import setup_agent_database
from adgn.props.db import get_session
from adgn.props.db.examples import Example
from adgn.props.db.models import Snapshot
from adgn.props.display import short_sha
from adgn.props.display import ColumnDef, build_table_from_schema
from adgn.props.splits import Split


def format_files_preview(files: list[str]) -> str:
    """Format file list with preview of first 3 and count."""
    if not files:
        return "(no files)"
    preview = ", ".join(files[:3])
    if len(files) > 3:
        preview += f", ... ({len(files)} total)"
    return preview


def main():
    """List training examples for critic evaluation."""
    # One-time setup (reads PG* env vars)
    setup_agent_database()
    console = Console()

    # Query the database
    with get_session() as session:
        # Get train examples with scope info
        query = (
            session.query(Example.snapshot_slug, Example.scope_hash, Example.scope)
            .join(Snapshot, Example.snapshot_slug == Snapshot.slug)
            .filter(Snapshot.split == Split.TRAIN)
            .order_by(Example.snapshot_slug, Example.scope_hash)
            .limit(10)
        )

        examples = query.all()
        total_count = query.count()

        console.print(f"\n[bold]Training examples (first 10 of {total_count}):[/bold]")

        columns: list[ColumnDef[Any, Any]] = [
            ColumnDef("Snapshot", lambda r: r.snapshot_slug, width=30),
            ColumnDef("Hash", lambda r: r.scope_hash, short_sha, width=8),
            ColumnDef("Scope", lambda r: r.scope, str, width=60),
        ]

        console.print(build_table_from_schema(examples, columns))


if __name__ == "__main__":
    main()
