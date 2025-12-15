"""Example: Query full-snapshot training examples.

Validation examples are ALWAYS full-snapshot (all files with issues).
To test on the same distribution as validation, query full-snapshot train examples.

Full-snapshot = the example that targets ALL files with issues in a snapshot.
This is the hardest example per snapshot (most TPs to catch).
"""

from adgn.props.agent_helpers import setup_agent_database
from adgn.props.db import get_session
from adgn.props.db.models import Example, Snapshot


def main():
    """List full-snapshot training examples (hardest per snapshot)."""
    setup_agent_database()

    with get_session() as session:
        # Query whole-snapshot examples (is_whole_snapshot=TRUE)
        # These target ALL files with issues in each snapshot
        full_snapshot_examples = (
            session.query(Example)
            .join(Snapshot)
            .filter(Snapshot.split == "train")
            .filter(Example.is_whole_snapshot == True)  # noqa: E712
            .order_by(Example.snapshot_slug)
            .all()
        )

        print(f"Full-Snapshot Train Examples ({len(full_snapshot_examples)} total)")
        print("=" * 80)
        print(f"{'Snapshot':<50}")
        print("-" * 80)

        for ex in full_snapshot_examples:
            print(f"{ex.snapshot_slug:<50}")

        if full_snapshot_examples:
            print("\nUsage with run_critic_on_example:")
            first_example = full_snapshot_examples[0]
            print(f"""
run_critic_on_example(
    snapshot_slug="{first_example.snapshot_slug}",
    files_hash=None,  # None = whole-snapshot (all files)
    prompt_sha256=your_prompt_hash,
    max_turns=30
)
""")


if __name__ == "__main__":
    main()
