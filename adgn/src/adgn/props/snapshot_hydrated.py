"""Hydrated snapshot - source code handle only (no issues, no manifest).

This is ONLY a handle to hydrated source code. All metadata (slug, manifest)
and issue data (TPs, FPs) must be loaded separately via:
- SnapshotSlug (passed separately)
- Database query for ORM Snapshot (for issues)
- SnapshotRegistry (for manifest if needed)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from adgn.props.paths import FileType


@dataclass
class HydratedSnapshot:
    """Handle to hydrated source code ONLY.

    This represents extracted/materialized source code in a temporary directory.
    It contains NO metadata (slug, manifest) and NO issue data (TPs, FPs).

    For issue data, query the database:
        from adgn.props.db import get_session
        from adgn.props.db.models import Snapshot

        with get_session() as session:
            snapshot_orm = session.query(Snapshot).filter_by(slug=slug).one()
            tps = snapshot_orm.true_positives
            fps = snapshot_orm.false_positives

    For manifest, use SnapshotRegistry:
        registry = SnapshotRegistry.from_package_resources()
        record = registry.get_record(slug)
        manifest = record.manifest
    """

    content_root: Path
    """Root directory containing extracted source code."""

    all_discovered_files: dict[Path, FileType]
    """All files discovered during hydration with their types."""
