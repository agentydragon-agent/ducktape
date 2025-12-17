"""Example: Working with Example objects (composite primary key pattern).

This script demonstrates how to work with Example objects, which have a
composite primary key instead of a single 'id' field.

Key schema details:
- Example has composite primary key: (snapshot_slug, scope_hash)
- No 'id' or 'key' attribute - use the tuple (snapshot_slug, scope_hash) as identifier
- Access via: example.snapshot_slug, example.scope_hash, example.scope
- Query pattern: session.query(Example).filter_by(snapshot_slug=..., scope_hash=...)
"""

from adgn.props.agent_helpers import setup_agent_database
from adgn.props.db import get_session
from adgn.props.db.examples import Example
from adgn.props.db.models import CriticRun, GraderRun, Snapshot
from adgn.props.display import short_sha

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

        for snapshot_slug, scope_hash in examples:
            example = session.query(Example).filter_by(
                snapshot_slug=snapshot_slug, scope_hash=scope_hash
            ).first()

            if example is None:
                print(f"❌ Example not found: {snapshot_slug} / {short_sha(scope_hash)}...")
                print()
                continue

            print(f"✓ {snapshot_slug} / {short_sha(scope_hash)}... | {example.scope}")

            # Count associated critic runs
            critic_count = (
                session.query(CriticRun)
                .filter_by(snapshot_slug=snapshot_slug, scope_hash=scope_hash)
                .count()
            )
            print(f"  Critic runs: {critic_count}")

            # Count associated grader runs
            grader_count = (
                session.query(GraderRun)
                .join(CriticRun, GraderRun.critic_run_id == CriticRun.id)
                .filter(
                    CriticRun.snapshot_slug == snapshot_slug,
                    CriticRun.scope_hash == scope_hash,
                )
                .count()
            )
            print(f"  Grader runs: {grader_count}")
            print()


if __name__ == "__main__":
    main()
