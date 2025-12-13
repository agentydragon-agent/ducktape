"""Example: Query full-snapshot training examples.

Validation examples are ALWAYS full-snapshot (all files with issues).
To test on the same distribution as validation, query full-snapshot train examples.

Full-snapshot = the example that targets ALL files with issues in a snapshot.
This is the hardest example per snapshot (most TPs to catch).
"""

from adgn.props.agent_helpers import setup_agent_database
from adgn.props.db import get_session
from adgn.props.db.models import Example, Snapshot
from sqlalchemy import func


def main():
    """List full-snapshot training examples (hardest per snapshot)."""
    setup_agent_database()

    with get_session() as session:
        # Query full-snapshot examples for each train snapshot
        # Full-snapshot = example with maximum number of files per snapshot

        # Subquery: count files per example
        file_counts = (
            session.query(
                Example.snapshot_slug,
                Example.files_hash,
                func.jsonb_array_length(Example.files).label('file_count')
            )
            .join(Snapshot)
            .filter(Snapshot.split == 'train')
            .subquery()
        )

        # Main query: get example with max file count per snapshot
        max_counts = (
            session.query(
                file_counts.c.snapshot_slug,
                func.max(file_counts.c.file_count).label('max_file_count')
            )
            .group_by(file_counts.c.snapshot_slug)
            .subquery()
        )

        full_snapshot_examples = (
            session.query(Example)
            .join(
                max_counts,
                Example.snapshot_slug == max_counts.c.snapshot_slug
            )
            .filter(
                func.jsonb_array_length(Example.files) == max_counts.c.max_file_count
            )
            .join(Snapshot)
            .filter(Snapshot.split == 'train')
            .order_by(Example.snapshot_slug)
            .all()
        )

        print(f"Full-Snapshot Train Examples ({len(full_snapshot_examples)} total)")
        print("=" * 80)
        print(f"{'Snapshot':<35} {'Files Hash':<10} {'File Count':<10}")
        print("-" * 80)

        for ex in full_snapshot_examples:
            snapshot_short = ex.snapshot_slug[:35]
            hash_short = ex.files_hash[:8]
            file_count = len(ex.files)
            print(f"{snapshot_short:<35} {hash_short:<10} {file_count:<10}")


if __name__ == "__main__":
    main()
