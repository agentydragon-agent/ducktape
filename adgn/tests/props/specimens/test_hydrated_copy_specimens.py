from __future__ import annotations

from adgn.props.hydration import SnapshotHydrator
from adgn.props.ids import SnapshotSlug


async def test_hydrated_copy_local_specimen_hydrates(test_specimens_hydrator: SnapshotHydrator, synced_test_db) -> None:
    """Hydrated local specimen workspace should contain the expected files.

    Uses test-trivial fixture to verify local specimen hydration works.
    """
    async with test_specimens_hydrator.hydrate(SnapshotSlug("test-fixtures/test-trivial")) as hydrated:
        assert hydrated.content_root.is_dir(), f"hydrated content root not a directory: {hydrated.content_root}"
        files = sorted(p.name for p in hydrated.content_root.iterdir() if p.is_file())
        # test-trivial has add.py and subtract.py
        assert "add.py" in files, f"Expected add.py in {hydrated.content_root}, got: {files}"
        assert "subtract.py" in files, f"Expected subtract.py in {hydrated.content_root}, got: {files}"


async def test_hydrated_copy_validation_specimen_has_expected_structure(
    test_specimens_hydrator: SnapshotHydrator, synced_test_db
) -> None:
    """Hydrated test-validation specimen should have expected structure.

    Uses test-validation fixture to verify specimen hydration works.
    """
    async with test_specimens_hydrator.hydrate(SnapshotSlug("test-fixtures/test-validation")) as hydrated:
        assert hydrated.content_root.is_dir(), f"hydrated content root not a directory: {hydrated.content_root}"
        # test-validation should have files
        files = list(hydrated.content_root.iterdir())
        assert len(files) > 0, f"expected non-empty directory: {hydrated.content_root}"
