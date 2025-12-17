"""Utilities for working with critic scopes."""

from __future__ import annotations

from pathlib import Path

from adgn.props.db import get_session
from adgn.props.db.models import Snapshot
from adgn.props.ids import SnapshotSlug
from adgn.props.models.critic_scopes import AllFilesScope, CriticScopeSpec, ExplicitFileScope


def resolve_scope_files(snapshot_slug: SnapshotSlug, scope: CriticScopeSpec) -> set[Path]:
    """Resolve a CriticScopeSpec to concrete file set.

    Args:
        snapshot_slug: Snapshot identifier (needed for AllFilesScope resolution)
        scope: The scope specification (discriminated union)

    Returns:
        Set of file paths in the scope
    """
    if isinstance(scope, AllFilesScope):
        # Load files with issues from database
        with get_session() as session:
            snapshot = session.query(Snapshot).filter_by(slug=snapshot_slug).one()
            return snapshot.files_with_issues()
    elif isinstance(scope, ExplicitFileScope):
        return {Path(f) for f in scope.files}
    else:
        raise ValueError(f"Unknown scope type: {type(scope)}")
