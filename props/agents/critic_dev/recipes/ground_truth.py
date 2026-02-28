"""Recipe: Querying ground truth (true positives and false positives).

Demonstrates how to explore what issues exist for snapshots, using the
ORM models and their class methods.
"""

from __future__ import annotations

from sqlalchemy.orm import Session, joinedload

from props.core.ids import SnapshotSlug
from props.core.splits import Split
from props.db.models import FalsePositive, Snapshot, TruePositive


def list_snapshots_by_split(session: Session, split: Split) -> list[Snapshot]:
    """List all snapshots for a given split."""
    return session.query(Snapshot).filter_by(split=split).order_by(Snapshot.slug).all()


def get_true_positives(session: Session, snapshot_slug: SnapshotSlug) -> list[TruePositive]:
    """Get all TPs for a snapshot with their occurrences eagerly loaded."""
    return (
        session.query(TruePositive)
        .options(joinedload(TruePositive.occurrences))
        .filter_by(snapshot_slug=snapshot_slug)
        .order_by(TruePositive.tp_id)
        .all()
    )


def get_false_positives(session: Session, snapshot_slug: SnapshotSlug) -> list[FalsePositive]:
    """Get all FPs for a snapshot with their occurrences eagerly loaded."""
    return (
        session.query(FalsePositive)
        .options(joinedload(FalsePositive.occurrences))
        .filter_by(snapshot_slug=snapshot_slug)
        .order_by(FalsePositive.fp_id)
        .all()
    )


def summarize_ground_truth(session: Session, snapshot_slug: SnapshotSlug) -> str:
    """Return a human-readable summary of all TPs and FPs for a snapshot."""
    tps = get_true_positives(session, snapshot_slug)
    fps = get_false_positives(session, snapshot_slug)

    lines = [f"Ground truth for {snapshot_slug}:", f"  {len(tps)} true positive(s), {len(fps)} false positive(s)", ""]

    for tp in tps:
        n_occ = len(tp.occurrences)
        lines.append(f"  TP {tp.tp_id}: {tp.rationale!r} ({n_occ} occurrence(s))")

    for fp in fps:
        n_occ = len(fp.occurrences)
        lines.append(f"  FP {fp.fp_id}: {fp.rationale!r} ({n_occ} occurrence(s))")

    return "\n".join(lines)
