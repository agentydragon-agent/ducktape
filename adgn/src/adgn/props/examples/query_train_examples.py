"""Example: Query training examples for testing prompts.

This script demonstrates how to list training examples (snapshot_slug, files_hash pairs)
that can be passed to run_critic_on_example.
"""

from adgn.props.agent_helpers import setup_agent_database
from adgn.props.db import get_session
from adgn.props.db.models import Example, Snapshot


def main():
    """List training examples for critic evaluation."""
    # One-time setup (reads PG* env vars)
    setup_agent_database()

    # Query the database
    with get_session() as session:
        # Get train examples with file counts for variety
        query = (
            session.query(Example.snapshot_slug, Example.files_hash, Example.files)
            .join(Snapshot, Example.snapshot_slug == Snapshot.slug)
            .filter(Snapshot.split == "train")
            .order_by(Example.snapshot_slug, Example.files_hash)
            .limit(10)
        )

        examples = query.all()

        print(f"Training examples (first 10 of {query.count()}):")
        for snapshot_slug, files_hash, files in examples:
            file_count = len(files)
            files_preview = ", ".join(files[:3])
            if len(files) > 3:
                files_preview += f", ... ({file_count} total)"
            print(f"  {snapshot_slug} / {files_hash[:16]}... ({file_count} files)")
            print(f"    Files: {files_preview}")


if __name__ == "__main__":
    main()
