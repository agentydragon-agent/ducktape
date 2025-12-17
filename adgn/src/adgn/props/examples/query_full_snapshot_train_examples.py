"""Example: Query full-snapshot training examples.

Validation examples are ALWAYS full-snapshot (all files with issues).
To test on the same distribution as validation, query full-snapshot train examples.

Full-snapshot = the example that targets ALL files with issues in a snapshot.
This is the hardest example per snapshot (most TPs to catch).
"""

from typing import Any

from rich.console import Console

from adgn.props.agent_helpers import setup_agent_database
from adgn.props.db import get_session
from adgn.props.db.examples import Example
from adgn.props.db.models import Snapshot
from adgn.props.display import ColumnDef, build_table_from_schema
from adgn.props.models.critic_scopes import ScopeKind
from adgn.props.splits import Split


def main():
    """List full-snapshot training examples (hardest per snapshot)."""
    setup_agent_database()
    console = Console()

    with get_session() as session:
        # Query whole-snapshot examples (scope_kind='entire_snapshot')
        # These target ALL files with issues in each snapshot
        full_snapshot_examples = (
            session.query(Example)
            .join(Snapshot)
            .filter(Snapshot.split == Split.TRAIN)
            .filter(Example.scope["kind"].astext == ScopeKind.ENTIRE_SNAPSHOT.value)
            .order_by(Example.snapshot_slug)
            .all()
        )

        console.print(f"\n[bold]Full-Snapshot Train Examples ({len(full_snapshot_examples)} total)[/bold]")

        columns: list[ColumnDef[Any, Any]] = [
            ColumnDef("Snapshot", lambda r: r.snapshot_slug, width=50),
            ColumnDef("Scope Hash", lambda r: r.scope_hash[:16], width=18),
        ]

        console.print(build_table_from_schema(full_snapshot_examples, columns))

        if full_snapshot_examples:
            first_example = full_snapshot_examples[0]
            console.print("\n[bold]Usage with run_critic_on_example:[/bold]")
            console.print(f"""
run_critic_on_example(
    snapshot_slug="{first_example.snapshot_slug}",
    scope_hash="{first_example.scope_hash}",  # Full-snapshot scope
    prompt_sha256=your_prompt_hash,
    max_turns=30
)
""")


if __name__ == "__main__":
    main()
