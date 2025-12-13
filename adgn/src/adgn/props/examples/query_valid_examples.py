"""Example: Query validation examples for measuring generalization.

This script demonstrates how to list validation examples (snapshot_slug, files_hash pairs)
for running critic evaluations and measuring validation recall.
"""

from adgn.props.agent_helpers import setup_agent_database
from adgn.props.db import get_session
from adgn.props.db.models import Example, Snapshot


def main():
    """List validation examples for critic evaluation."""
    # One-time setup (reads PG* env vars)
    setup_agent_database()

    # Query the database
    with get_session() as session:
        # Get valid examples
        query = (
            session.query(Example.snapshot_slug, Example.files_hash, Example.files)
            .join(Snapshot, Example.snapshot_slug == Snapshot.slug)
            .filter(Snapshot.split == "valid")
            .order_by(Example.snapshot_slug, Example.files_hash)
        )

        examples = query.all()

        print(f"Validation examples ({len(examples)} total):")
        for snapshot_slug, files_hash, files in examples:
            file_count = len(files)
            files_preview = ", ".join(files[:3])
            if len(files) > 3:
                files_preview += f", ... ({file_count} total)"
            print(f"  {snapshot_slug} / {files_hash[:16]}... ({file_count} files)")
            print(f"    Files: {files_preview}")


if __name__ == "__main__":
    main()
