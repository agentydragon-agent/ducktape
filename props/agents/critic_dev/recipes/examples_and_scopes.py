"""Recipe: Working with examples and scopes.

Demonstrates how to list training examples, look up examples by spec,
and construct ExampleSpec objects.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from props.core.ids import SnapshotSlug
from props.core.models.examples import ExampleSpec, SingleFileSetExample, WholeSnapshotExample
from props.core.splits import Split
from props.db.examples import Example, get_examples_for_split


def list_train_examples(session: Session) -> list[Example]:
    """List all training examples, ordered deterministically.

    Uses get_examples_for_split() — the canonical entrypoint for loading
    training data. Examples are ordered by (snapshot_slug, example_kind,
    files_hash NULLS FIRST).
    """
    return get_examples_for_split(session, Split.TRAIN)


def get_example_details(session: Session, spec: ExampleSpec) -> Example:
    """Look up an Example from an ExampleSpec. Raises if not found."""
    return Example.from_spec(session, spec)


def build_example_spec(snapshot_slug: str, files_hash: str | None = None) -> ExampleSpec:
    """Construct an ExampleSpec from slug and optional files_hash.

    If files_hash is provided, creates a SingleFileSetExample (per-file scope).
    Otherwise, creates a WholeSnapshotExample (full-specimen scope).
    """
    slug = SnapshotSlug(snapshot_slug)
    if files_hash is not None:
        return SingleFileSetExample(snapshot_slug=slug, files_hash=files_hash)
    return WholeSnapshotExample(snapshot_slug=slug)
