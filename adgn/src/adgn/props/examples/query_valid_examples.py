"""Example: Query validation snapshots for measuring generalization.

This script demonstrates how to list validation snapshots.

Note: Validation examples table is hidden (train-only via RLS).
Query snapshots table instead.
"""

from typing import Any

from rich.console import Console

from adgn.props.agent_helpers import setup_agent_database
from adgn.props.db import get_session
from adgn.props.db.models import Snapshot
from adgn.props.display import ColumnDef, build_table_from_schema
from adgn.props.splits import Split


def main():
    """List validation snapshots."""
    # One-time setup (reads PG* env vars)
    setup_agent_database()
    console = Console()

    # Query the database
    with get_session() as session:
        # Get valid snapshots (examples table is train-only via RLS)
        query = session.query(Snapshot.slug).filter(Snapshot.split == Split.VALID).order_by(Snapshot.slug)

        snapshots = query.all()

        console.print(f"\n[bold]Validation snapshots ({len(snapshots)} total):[/bold]")

        columns: list[ColumnDef[Any, Any]] = [
            ColumnDef("Snapshot Slug", lambda r: r[0], width=40),
        ]

        console.print(build_table_from_schema(snapshots, columns))


if __name__ == "__main__":
    main()
