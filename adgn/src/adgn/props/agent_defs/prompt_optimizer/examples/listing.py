"""List examples and snapshots by split and scope.

This module demonstrates how to query the database for examples and snapshots,
with filtering by split (TRAIN/VALID/TEST) and scope kind (full-snapshot vs per-file).

IMPORTANT: These functions PRINT output to console - they don't return values.
For programmatic access, use direct database queries (see examples in function bodies).

Available display functions (call without arguments, they print to console):
- list_train_examples() - Show training examples for critic evaluation
- list_valid_snapshots() - Show validation snapshots (examples table may be RLS-blocked)
- list_full_snapshot_train_examples() - Show full-snapshot training examples
- show_dataset_scale() - Count examples by split and scope kind

Note: There is NO `list_examples()` function. Use the specific functions above.
For programmatic access, query the database directly:
```python
from adgn.props.db import get_session
from adgn.props.db.examples import Example
from adgn.props.db.models import Snapshot
from adgn.props.splits import Split

with get_session() as session:
    # Query train examples
    examples = session.query(Example).join(Snapshot).filter(Snapshot.split == Split.TRAIN).all()
```

In whole-repo mode, the examples table is RLS-blocked for VALID/TEST splits.
Use list_valid_snapshots() instead.
"""

from typing import Any

from rich.console import Console

from adgn.props.db import get_session
from adgn.props.db.examples import Example, count_available_examples_by_scope_all
from adgn.props.db.models import Snapshot
from adgn.props.display import ColumnDef, build_table_from_schema, short_sha
from adgn.props.models.examples import ExampleKind
from adgn.props.splits import Split


def format_files_preview(files: list[str]) -> str:
    """Format file list with preview of first 3 and count."""
    if not files:
        return "(no files)"
    preview = ", ".join(files[:3])
    if len(files) > 3:
        preview += f", ... ({len(files)} total)"
    return preview


def list_train_examples(limit: int = 10) -> None:
    """List training examples for critic evaluation.

    Shows snapshot_slug, example_kind, files_hash that can be used to build ExampleSpec.
    """
    console = Console()

    with get_session() as session:
        query = (
            session.query(Example.snapshot_slug, Example.example_kind, Example.files_hash)
            .join(Snapshot, Example.snapshot_slug == Snapshot.slug)
            .filter(Snapshot.split == Split.TRAIN)
            .order_by(Example.snapshot_slug, Example.example_kind, Example.files_hash.nullsfirst())
            .limit(limit)
        )

        examples = query.all()
        total_count = (
            session.query(Example)
            .join(Snapshot, Example.snapshot_slug == Snapshot.slug)
            .filter(Snapshot.split == Split.TRAIN)
            .count()
        )

        console.print(f"\n[bold]Training examples (first {limit} of {total_count}):[/bold]")

        columns: list[ColumnDef[Any, Any]] = [
            ColumnDef("Snapshot", lambda r: r.snapshot_slug, width=30),
            ColumnDef("Kind", lambda r: r.example_kind.value, width=18),
            ColumnDef("FileSet", lambda r: str(r.files_hash) if r.files_hash else "-", width=10),
        ]

        console.print(build_table_from_schema(examples, columns))


def list_valid_snapshots() -> None:
    """List validation snapshots.

    Note: Validation examples table may be RLS-blocked (train-only in whole-repo mode).
    Query snapshots table instead.
    """
    console = Console()

    with get_session() as session:
        query = session.query(Snapshot.slug).filter(Snapshot.split == Split.VALID).order_by(Snapshot.slug)
        snapshots = query.all()

        console.print(f"\n[bold]Validation snapshots ({len(snapshots)} total):[/bold]")

        columns: list[ColumnDef[Any, Any]] = [
            ColumnDef("Snapshot Slug", lambda r: r[0], width=40),
        ]

        console.print(build_table_from_schema(snapshots, columns))


def list_full_snapshot_train_examples() -> None:
    """List full-snapshot training examples (hardest per snapshot).

    Full-snapshot = the example that targets ALL files with issues in a snapshot.
    Validation examples are ALWAYS full-snapshot. To test on the same distribution
    as validation, use full-snapshot train examples.
    """
    console = Console()

    with get_session() as session:
        full_snapshot_examples = (
            session.query(Example)
            .join(Snapshot, Example.snapshot_slug == Snapshot.slug)
            .filter(Snapshot.split == Split.TRAIN)
            .filter(Example.example_kind == ExampleKind.WHOLE_SNAPSHOT)
            .order_by(Example.snapshot_slug)
            .all()
        )

        console.print(f"\n[bold]Full-Snapshot Train Examples ({len(full_snapshot_examples)} total)[/bold]")

        columns: list[ColumnDef[Any, Any]] = [
            ColumnDef("Snapshot", lambda r: r.snapshot_slug, width=50),
            ColumnDef("Kind", lambda r: r.example_kind.value, width=18),
        ]

        console.print(build_table_from_schema(full_snapshot_examples, columns))

        if full_snapshot_examples:
            first_example = full_snapshot_examples[0]
            console.print("\n[bold]Usage with run_critic:[/bold]")
            console.print(f"""
from helpers import run_critic
from adgn.props.models.examples import WholeSnapshotExample

output = await run_critic(
    definition_id="critic",  # or your custom definition ID
    example=WholeSnapshotExample(snapshot_slug="{first_example.snapshot_slug}"),
    max_turns=30
)
print(f"Critic run: {{output.critic_run_id}}")
""")


def show_dataset_scale() -> None:
    """Count examples grouped by split and example kind.

    Key schema details:
    - Example has composite primary key: (snapshot_slug, example_kind, files_hash)
    - Split information comes from the related Snapshot (via snapshot_obj.split)
    - Example kind: whole_snapshot or file_set
    """
    with get_session() as session:
        counts = count_available_examples_by_scope_all(
            session, [Split.TRAIN, Split.VALID, Split.TEST]
        )

        print("=== Dataset sizes by split and scope kind ===")
        for (split, scope_kind), count in counts.items():
            print(f"{split.value:5} {scope_kind.value:20} {count}")


def main():
    """Run all listing examples."""
    show_dataset_scale()
    print()
    list_train_examples()
    print()
    list_valid_snapshots()
    print()
    list_full_snapshot_train_examples()


if __name__ == "__main__":
    main()
