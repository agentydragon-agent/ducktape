"""Fixtures for clustering RLS tests."""

from adgn.props.db.models import Snapshot
from adgn.props.ids import SnapshotSlug
from adgn.props.splits import Split


def make_test_snapshot(slug: str, commit: str) -> Snapshot:
    """Helper to create a test snapshot with standard git source.

    Args:
        slug: Snapshot slug (e.g., "test/my-snapshot")
        commit: Git commit SHA

    Returns:
        Snapshot instance (not yet added to session)
    """
    return Snapshot(
        slug=SnapshotSlug(slug),
        split=Split.TRAIN,
        source={"vcs": "git", "url": "https://example.com/repo.git", "commit": commit},
    )
