"""Example: Query validation snapshots for measuring generalization.

This script demonstrates how to list validation snapshots.

Note: Validation examples table is hidden (train-only via RLS).
Query snapshots table instead.
"""

from adgn.props.agent_helpers import setup_agent_database
from adgn.props.db import get_session
from adgn.props.db.models import Snapshot


def main():
    """List validation snapshots."""
    # One-time setup (reads PG* env vars)
    setup_agent_database()

    # Query the database
    with get_session() as session:
        # Get valid snapshots (examples table is train-only via RLS)
        query = session.query(Snapshot.slug).filter(Snapshot.split == "valid").order_by(Snapshot.slug)

        snapshots = query.all()

        print(f"Validation snapshots ({len(snapshots)} total):\n")
        for (slug,) in snapshots:
            print(f"  {slug}")


if __name__ == "__main__":
    main()
