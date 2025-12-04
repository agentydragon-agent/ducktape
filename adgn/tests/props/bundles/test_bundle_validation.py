"""Test that specimen bundles don't include specimen issue files."""

from fnmatch import fnmatch
from pathlib import Path

import pytest

from adgn.props.models.snapshot import GitSource
from adgn.props.snapshot_registry import SnapshotRegistry, resolve_bundle_url

# Size limit for files in bundle (2MB)
MAX_FILE_SIZE = 2 * 1024 * 1024

# Overall bundle size limit (10MB)
MAX_BUNDLE_SIZE = 10 * 1024 * 1024


@pytest.fixture(scope="session")
def specimens_base_for_bundles() -> Path:
    """Base directory containing all specimens."""
    registry = SnapshotRegistry.from_package_resources()
    return registry.base_path


def pytest_generate_tests(metafunc):
    """Dynamically parametrize tests with specimens (pytest collection-time hook).

    WHY THIS IS MAGIC (and can't be avoided easily):
    - Runs during pytest collection (before fixtures are available)
    - Filters specimens by source type (Git bundles) at collection time
    - Creates test cases dynamically based on discovered specimens

    CLEANER ALTERNATIVE (but requires manual maintenance):
    - Create explicit list: BUNDLE_SPECIMENS = ["slug1", "slug2", ...]
    - Use: @pytest.mark.parametrize("specimen_record", BUNDLE_SPECIMENS, indirect=True)
    - Trade-off: Less magic but requires updating list when specimens change

    CURRENT APPROACH:
    - Auto-discovers Git bundle specimens from registry
    - Filters to only file:// bundles (local files)
    - No manual list maintenance needed
    """
    if "specimen_record" not in metafunc.fixturenames and "hydrated_specimen" not in metafunc.fixturenames:
        return

    # Create registry at collection time (lightweight, no specimens loaded yet)
    registry = SnapshotRegistry.from_package_resources()
    all_specimen_slugs = registry.snapshot_slugs

    # Filter to Git bundle specimens with file:// URLs
    bundle_specimen_slugs = []
    for slug in all_specimen_slugs:
        # Fast path: load only manifest (no Jsonnet) during collection
        manifest_path, manifest = registry.load_manifest_only(slug)

        if isinstance(manifest.source, GitSource):
            bundle_url = resolve_bundle_url(manifest_path, manifest.source.url)
            if bundle_url.startswith("file://"):
                bundle_specimen_slugs.append(slug)

    # Parametrize tests with filtered specimen slugs
    metafunc.parametrize(
        "specimen_record", sorted(bundle_specimen_slugs), ids=sorted(bundle_specimen_slugs), indirect=True
    )


@pytest.fixture
async def specimen_record(request, production_specimens_registry):
    """Fixture that loads a specimen record without hydration.

    Parameter: slug (string)
    Returns: SnapshotRecord
    """
    slug = request.param
    async with production_specimens_registry.load_and_hydrate(slug) as hydrated:
        return hydrated.record


@pytest.fixture
async def hydrated_specimen(specimen_record):
    """Fixture that yields a hydrated specimen checkout directory.

    Derives from specimen_record fixture.
    Yields: Path to checkout directory
    """
    async with specimen_record.hydrated_copy() as checkout_dir:
        yield checkout_dir


def test_bundle_exists(specimen_record) -> None:
    """Verify bundle file exists for specimen."""
    assert isinstance(specimen_record.manifest.source, GitSource)

    bundle_url = resolve_bundle_url(specimen_record.snapshot_path, specimen_record.manifest.source.url)
    bundle_path = Path(bundle_url.removeprefix("file://"))

    assert bundle_path.exists(), f"Bundle not found at {bundle_path}"
    assert bundle_path.stat().st_size > 0, f"Bundle file is empty: {bundle_path}"


@pytest.mark.asyncio
async def test_bundle_excludes_libsonnet_files(specimen_record, hydrated_specimen) -> None:
    """Verify no .libsonnet files (specimen issues) are included in any commit.

    This test ensures that specimen bundles don't recursively include the specimen
    issue files themselves. The bundle should contain only the code snapshots, not
    the issue definitions that describe problems in those snapshots.
    """
    libsonnet_files = list(hydrated_specimen.rglob("*.libsonnet"))

    assert len(libsonnet_files) == 0, (
        f"Found {len(libsonnet_files)} .libsonnet files in {specimen_record.slug}:\n"
        + "\n".join(f"  - {f.relative_to(hydrated_specimen)}" for f in libsonnet_files[:10])
    )


@pytest.mark.asyncio
async def test_bundle_excludes_specimen_metadata(specimen_record, hydrated_specimen) -> None:
    """Verify no specimen metadata files (libsonnet issues, snapshots.yaml) are included.

    This ensures the specimens/ directory itself is not in the bundle.
    """
    specimens_dir = hydrated_specimen / "adgn" / "src" / "adgn" / "props" / "specimens"

    assert not specimens_dir.exists(), (
        f"specimens/ directory found in {specimen_record.slug}. "
        f"The bundle should exclude adgn/src/adgn/props/specimens/ to prevent recursive bundling."
    )


@pytest.mark.asyncio
async def test_bundle_excludes_large_files(specimen_record, hydrated_specimen) -> None:
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
        msg_parts = [f"Found files >2MB in {specimen_record.slug}:"]
        for path, size in large_files:
            size_mb = size / (1024 * 1024)
            msg_parts.append(f"\n  {size_mb:.2f} MB: {path}")
        pytest.fail("".join(msg_parts))


@pytest.mark.asyncio
async def test_bundle_excludes_bundle_files(specimen_record, hydrated_specimen) -> None:
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

    assert not bundle_files, f"Found .bundle files recursively included in {specimen_record.slug}:\n" + "\n".join(
        f"  - {path}" for path in bundle_files
    )


def test_bundle_size_reasonable(specimen_record) -> None:
    """Verify bundle file size is reasonable (<10MB).

    Bundle should typically be 1-6MB. If it's >10MB, something is wrong
    (likely recursive bundle inclusion or large files).
    """
    assert isinstance(specimen_record.manifest.source, GitSource)

    bundle_url = resolve_bundle_url(specimen_record.snapshot_path, specimen_record.manifest.source.url)
    bundle_path = Path(bundle_url.removeprefix("file://"))

    bundle_size = bundle_path.stat().st_size

    assert bundle_size < MAX_BUNDLE_SIZE, (
        f"Bundle {bundle_path.name} size {bundle_size / (1024 * 1024):.2f} MB exceeds "
        f"reasonable limit of {MAX_BUNDLE_SIZE / (1024 * 1024):.0f} MB. "
        "Check for recursive bundle inclusion or large files."
    )


@pytest.mark.asyncio
async def test_specimen_respects_exclusion_patterns(specimen_record, hydrated_specimen) -> None:
    """Verify no specimen includes files matching its exclusion patterns.

    This ensures bundle.exclude patterns in snapshots.yaml are properly respected.
    """
    bundle_config = specimen_record.manifest.bundle
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
        f"Snapshot {specimen_record.slug} includes files matching exclusion patterns:\n"
        + "\n".join(f"  {path} matches pattern '{pattern}'" for path, pattern in violations[:10])
        + (f"\n  ... and {len(violations) - 10} more" if len(violations) > 10 else "")
    )
