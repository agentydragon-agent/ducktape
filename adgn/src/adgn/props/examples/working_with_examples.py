"""Example: Working with Example objects (composite primary key pattern).

This script demonstrates how to work with Example objects, which have a
composite primary key instead of a single 'id' field.

Key schema details:
- Example has composite primary key: (snapshot_slug, files_hash)
- No 'id' or 'key' attribute - use the tuple (snapshot_slug, files_hash) as identifier
- Access via: example.snapshot_slug, example.files_hash, example.files
- Query pattern: session.query(Example).filter_by(snapshot_slug=..., files_hash=...)
"""

from adgn.props.agent_helpers import setup_agent_database
from adgn.props.db import get_session
from adgn.props.db.models import CriticRun, Example, GraderRun, Snapshot

# Example keys to query (can be patched in tests)
examples = [
    ("ducktape/2025-12-04-00", "2218c0dacb6594985f72b9c78880aea341de110ce28a1924054399aebc24da23"),
    ("crush/2025-08-30-internal_db", "733628142f29d9df2a775332d677ba976ffafbd95f1ceb3908cdf94a6a6af4ca"),
]


def main():
    """Query details for specific examples."""
    # One-time setup (reads PG* env vars)
    setup_agent_database()

    with get_session() as session:

        print("Querying example details:")
        print()

        for snapshot_slug, files_hash in examples:
            # Query the Example object
            example = session.query(Example).filter_by(
                snapshot_slug=snapshot_slug, files_hash=files_hash
            ).first()

            if not example:
                print(f"❌ Example not found: {snapshot_slug} / {files_hash[:16]}...")
                continue

            print(f"✓ {snapshot_slug} / {files_hash[:16]}...")
            print(f"  Files ({len(example.files)}): {', '.join(example.files[:3])}")

            # Count associated critic runs
            critic_count = (
                session.query(CriticRun)
                .filter_by(snapshot_slug=snapshot_slug, files_hash=files_hash)
                .count()
            )
            print(f"  Critic runs: {critic_count}")

            # Count associated grader runs
            grader_count = (
                session.query(GraderRun)
                .join(CriticRun, GraderRun.critique_id == CriticRun.critique_id)
                .filter(
                    CriticRun.snapshot_slug == snapshot_slug,
                    CriticRun.files_hash == files_hash,
                )
                .count()
            )
            print(f"  Grader runs: {grader_count}")
            print()


if __name__ == "__main__":
    main()
