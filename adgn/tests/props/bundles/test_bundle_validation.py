"""Test that specimen bundles don't include specimen issue files."""

from fnmatch import fnmatch
from pathlib import Path

import pytest

from adgn.props.db.sync import get_specimens_base_path, load_manifests_from_yaml
from adgn.props.hydration import SnapshotHydrator, resolve_bundle_url
from adgn.props.ids import get_snapshot_manifest_path
from adgn.props.models.snapshot import GitSource

# Size limit for files in bundle (2MB)
MAX_FILE_SIZE = 2 * 1024 * 1024

# Overall bundle size limit (10MB)
MAX_BUNDLE_SIZE = 10 * 1024 * 1024


@pytest.fixture(scope="session")
def specimens_base_for_bundles() -> Path:
    """Base directory containing all specimens."""
    return get_specimens_base_path()


def pytest_generate_tests(metafunc):
    """Dynamically parametrize tests with specimens (pytest collection-time hook).

    WHY THIS IS MAGIC (and can't be avoided easily):
    - Runs during pytest collection (before fixtures are available)
    - Filters specimens by source type (Git bundles) at collection time
    - Creates test cases dynamically based on discovered specimens

    CLEANER ALTERNATIVE (but requires manual maintenance):
    - Create explicit list: BUNDLE_SPECIMENS = ["slug1", "slug2", ...]
    - Use: @pytest.mark.parametrize("snapshot_slug", BUNDLE_SPECIMENS, indirect=True)
    - Trade-off: Less magic but requires updating list when specimens change

    CURRENT APPROACH:
    - Auto-discovers Git bundle specimens from snapshots.yaml
    - Filters to only file:// bundles (local files)
    - No manual list maintenance needed
    """
    if "snapshot_slug" not in metafunc.fixturenames and "hydrated_specimen" not in metafunc.fixturenames:
        return

    # Load manifests at collection time
    base_path = get_specimens_base_path()
    manifests = load_manifests_from_yaml(base_path)

    # Filter to Git bundle specimens with file:// URLs
    bundle_specimen_slugs = []
    for slug, manifest in manifests.items():
        if isinstance(manifest.source, GitSource):
            manifest_path = get_snapshot_manifest_path(base_path, slug)
            bundle_url = resolve_bundle_url(manifest_path, manifest.source.url)
            if bundle_url.startswith("file://"):
                bundle_specimen_slugs.append(slug)

    # Parametrize tests with filtered specimen slugs
    metafunc.parametrize(
        "snapshot_slug", sorted(bundle_specimen_slugs), ids=sorted(bundle_specimen_slugs), indirect=True
    )


@pytest.fixture
def snapshot_slug(request):
    """Parametrized fixture providing snapshot slug."""
    return request.param


@pytest.fixture
def snapshot_manifest(snapshot_slug, specimens_base_for_bundles):
    """Fixture that loads snapshot manifest from slug."""
    manifests = load_manifests_from_yaml(specimens_base_for_bundles)
    return manifests[snapshot_slug]


@pytest.fixture
def snapshot_path(snapshot_slug, specimens_base_for_bundles):
    """Fixture that loads snapshot path from slug."""
    return get_snapshot_manifest_path(specimens_base_for_bundles, snapshot_slug)


@pytest.fixture
async def hydrated_specimen(snapshot_slug, specimens_base_for_bundles, synced_test_db):
    """Fixture that yields a hydrated specimen checkout directory.

    Derives from snapshot slug using SnapshotHydrator.
    Yields: Path to checkout directory (content_root from HydratedSnapshot)
    Depends on synced_test_db to ensure database has production specimens synced before hydration.
    """
    hydrator = SnapshotHydrator(specimens_base_for_bundles)
    async with hydrator.hydrate(snapshot_slug) as hydrated:
        yield hydrated.content_root


def test_bundle_exists(snapshot_manifest, snapshot_path) -> None:
    """Verify bundle file exists for specimen."""
    assert isinstance(snapshot_manifest.source, GitSource)

    bundle_url = resolve_bundle_url(snapshot_path, snapshot_manifest.source.url)
    bundle_path = Path(bundle_url.removeprefix("file://"))

    assert bundle_path.exists(), f"Bundle not found at {bundle_path}"
    assert bundle_path.stat().st_size > 0, f"Bundle file is empty: {bundle_path}"


async def test_bundle_excludes_libsonnet_files(snapshot_slug, hydrated_specimen) -> None:
    """Verify no .libsonnet files (specimen issues) are included in any commit.

    This test ensures that specimen bundles don't recursively include the specimen
    issue files themselves. The bundle should contain only the code snapshots, not
    the issue definitions that describe problems in those snapshots.

    Note: Test fixture .libsonnet files (under tests/) are allowed.
    """
    all_libsonnet = list(hydrated_specimen.rglob("*.libsonnet"))

    # Filter to only specimen metadata (not test fixtures)
    specimens_path = "src/adgn/props/specimens"
    libsonnet_files = [f for f in all_libsonnet if specimens_path in str(f.relative_to(hydrated_specimen))]

    assert len(libsonnet_files) == 0, (
        f"Found {len(libsonnet_files)} specimen .libsonnet files in {snapshot_slug}:\n"
        + "\n".join(f"  - {f.relative_to(hydrated_specimen)}" for f in libsonnet_files[:10])
    )


async def test_bundle_excludes_specimen_metadata(snapshot_slug, hydrated_specimen) -> None:
    """Verify no specimen metadata files (libsonnet issues, snapshots.yaml) are included.

    This ensures the specimens/ directory itself is not in the bundle.
    """
    specimens_dir = hydrated_specimen / "adgn" / "src" / "adgn" / "props" / "specimens"

    assert not specimens_dir.exists(), (
        f"specimens/ directory found in {snapshot_slug}. "
        f"The bundle should exclude adgn/src/adgn/props/specimens/ to prevent recursive bundling."
    )


async def test_bundle_excludes_large_files(snapshot_slug, hydrated_specimen) -> None:
    """Verify no files larger than 2MB are included in any commit.

    This prevents bundle bloat from large binaries or other files that
    shouldn't be in code snapshots.
    """
    large_files = []
    for file_path in hydrated_specimen.rglob("*"):
        if file_path.is_file():
            size = file_path.stat().st_size
            if size > MAX_FILE_SIZE:
                rel_path = file_path.relative_to(hydrated_specimen)
                large_files.append((str(rel_path), size))

    if large_files:
        msg_parts = [f"Found files >2MB in {snapshot_slug}:"]
        for path, size in large_files:
            size_mb = size / (1024 * 1024)
            msg_parts.append(f"\n  {size_mb:.2f} MB: {path}")
        pytest.fail("".join(msg_parts))


async def test_bundle_excludes_bundle_files(snapshot_slug, hydrated_specimen) -> None:
    """Verify no .bundle files are recursively included in any commit.

    This is a critical check - recursive bundle inclusion can cause exponential
    bundle growth and is a clear sign of incorrect exclusion patterns.
    """
    bundle_files = [str(f.relative_to(hydrated_specimen)) for f in hydrated_specimen.rglob("*.bundle")]
    bundle_files.extend(
        [
            str(f.relative_to(hydrated_specimen))
            for f in hydrated_specimen.rglob("*")
            if f.is_file() and "snapshots.bundle" in f.name
        ]
    )

    assert not bundle_files, f"Found .bundle files recursively included in {snapshot_slug}:\n" + "\n".join(
        f"  - {path}" for path in bundle_files
    )


def test_bundle_size_reasonable(snapshot_manifest, snapshot_path) -> None:
    """Verify bundle file size is reasonable (<10MB).

    Bundle should typically be 1-6MB. If it's >10MB, something is wrong
    (likely recursive bundle inclusion or large files).
    """
    assert isinstance(snapshot_manifest.source, GitSource)

    bundle_url = resolve_bundle_url(snapshot_path, snapshot_manifest.source.url)
    bundle_path = Path(bundle_url.removeprefix("file://"))

    bundle_size = bundle_path.stat().st_size

    assert bundle_size < MAX_BUNDLE_SIZE, (
        f"Bundle {bundle_path.name} size {bundle_size / (1024 * 1024):.2f} MB exceeds "
        f"reasonable limit of {MAX_BUNDLE_SIZE / (1024 * 1024):.0f} MB. "
        "Check for recursive bundle inclusion or large files."
    )


async def test_specimen_respects_exclusion_patterns(snapshot_slug, snapshot_manifest, hydrated_specimen) -> None:
    """Verify no specimen includes files matching its exclusion patterns.

    This ensures bundle.exclude patterns in snapshots.yaml are properly respected.
    """
    bundle_config = snapshot_manifest.bundle
    if not bundle_config or not bundle_config.exclude:
        # No exclusions to check
        return

    # Collect all file paths
    all_paths = [f.relative_to(hydrated_specimen) for f in hydrated_specimen.rglob("*") if f.is_file()]

    # Check if any paths match exclusion patterns
    violations = []
    for path in all_paths:
        path_str = str(path)
        for pattern in bundle_config.exclude:
            # Normalize pattern (remove trailing /)
            normalized_pattern = pattern.rstrip("/")
            # Check if path starts with pattern or matches glob
            if (
                path_str.startswith(normalized_pattern + "/")
                or fnmatch(path_str, normalized_pattern + "/*")
                or path_str == normalized_pattern
            ):
                violations.append((path_str, pattern))

    assert not violations, (
        f"Snapshot {snapshot_slug} includes files matching exclusion patterns:\n"
        + "\n".join(f"  {path} matches pattern '{pattern}'" for path, pattern in violations[:10])
        + (f"\n  ... and {len(violations) - 10} more" if len(violations) > 10 else "")
    )
