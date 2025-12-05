"""Source code hydration for snapshots (no issue loading).

SnapshotHydrator extracts snapshot source code to temporary directories.
Issues must be loaded separately from database via ORM Snapshot model.

This is the public API for runtime components (grader, critic, GEPA, CLI).
For sync operations, use db.sync.SyncLoader (private).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
import shutil

import yaml

from .ids import SnapshotSlug, split_snapshot_slug
from .models.snapshot import SnapshotDoc
from .paths import classify_path
from .prop_utils import specimens_definitions_root
from .snapshot_hydrated import HydratedSnapshot
from .snapshot_registry import resolve_source_root


class SnapshotHydrator:
    """Public API for source code hydration only (no issue loading).

    Used by runtime components (grader, critic, GEPA, CLI) to extract
    source code to temporary directories.

    Issues must be loaded separately from database via ORM Snapshot model.
    """

    def __init__(self, base_path: Path):
        """Initialize hydrator with base path to specimens directory.

        Args:
            base_path: Root directory containing snapshots (specimens/)
        """
        self._base_path = base_path
        self._manifests = self._load_all_manifests()

    @classmethod
    def from_package_resources(cls) -> SnapshotHydrator:
        """Create hydrator from package resources (specimens/)."""
        return cls(specimens_definitions_root())

    def _load_all_manifests(self) -> dict[SnapshotSlug, SnapshotDoc]:
        """Load all snapshot manifests from snapshots.yaml."""
        config_path = self._base_path / "snapshots.yaml"
        if not config_path.exists():
            raise FileNotFoundError(f"Snapshots config not found: {config_path}")

        with config_path.open() as f:
            raw_config = yaml.safe_load(f) or {}

        manifests = {}
        for slug_str, raw_manifest in raw_config.items():
            slug = SnapshotSlug(slug_str)
            manifests[slug] = SnapshotDoc.model_validate(raw_manifest)

        return manifests

    def _get_snapshot_path(self, slug: SnapshotSlug) -> Path:
        """Get absolute path to snapshot's _snapshot file.

        Returns:
            Resolved absolute path inside snapshot directory (for URL resolution)
        """
        repo, version = split_snapshot_slug(slug)
        return (self._base_path / repo / version / "_snapshot").resolve()

    @asynccontextmanager
    async def hydrate(self, slug: SnapshotSlug) -> AsyncIterator[HydratedSnapshot]:
        """Hydrate source code only (no issue data).

        Returns HydratedSnapshot with:
        - content_root: Path to extracted source
        - all_discovered_files: dict[Path, FileType] relative paths

        Issues must be loaded separately from database via ORM.

        Args:
            slug: Snapshot slug like "ducktape/2025-11-26-00"

        Yields:
            HydratedSnapshot with source paths only (no record/issues)

        Example:
            hydrator = SnapshotHydrator.from_package_resources()
            async with hydrator.hydrate("ducktape/2025-11-26-00") as hydrated:
                workspace = hydrated.content_root
                files = hydrated.all_discovered_files

                # Load issues from database separately
                session = get_session()
                snapshot = session.query(Snapshot).filter_by(slug=slug).one()
                tps = snapshot.true_positives  # ORM relationship
                fps = snapshot.false_positives
        """
        if slug not in self._manifests:
            raise FileNotFoundError(f"Snapshot '{slug}' not found in registry")

        snapshot_path = self._get_snapshot_path(slug)
        manifest = self._manifests[slug]

        # Extract source to temp directory
        hydrated_root = resolve_source_root(manifest, snapshot_path)

        try:
            # Build file map (for validation contexts, Docker mounts, etc.)
            all_discovered_files = {
                p.relative_to(hydrated_root): classify_path(p) for p in hydrated_root.rglob("*") if p.is_file()
            }

            # Yield hydrated snapshot - source paths only (no issues!)
            yield HydratedSnapshot(content_root=hydrated_root, all_discovered_files=all_discovered_files)
        finally:
            # Clean up hydrated snapshot
            shutil.rmtree(
                hydrated_root.parent if hydrated_root.parent.name.startswith("adgn-snapshot-") else hydrated_root,
                ignore_errors=True,
            )
