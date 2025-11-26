"""Test that specimen bundles don't include specimen issue files."""

from pathlib import Path
import subprocess

import pygit2
import pytest

from adgn.props.models.specimen import GitSource
from adgn.props.specimens.registry import SpecimenRegistry, find_specimens_base, list_specimen_names


@pytest.fixture(scope="session")
def specimens_base() -> Path:
    """Base directory containing all specimens."""
    return find_specimens_base()


def _resolve_bundle_url(manifest_path: Path, source_url: str) -> str:
    """Resolve bundle URL using existing registry logic.

    Handles relative file:// URLs like the registry does.
    """
    url = source_url
    if url.startswith("file://"):
        file_path = url.removeprefix("file://")
        # If it's a relative path, resolve it relative to manifest directory
        if not file_path.startswith("/"):
            resolved_path = (manifest_path.parent / file_path).resolve()
            url = f"file://{resolved_path}"
    return url


def _find_bundle_and_refs(specimens_base: Path) -> list[tuple[str, str]]:
    """Find all bundles and their specimen refs.

    Returns list of (bundle_url, ref) tuples where bundle_url is absolute file:// URL.
    Only includes specimens with GitSource (which have bundle URLs).
    """
    bundle_refs = []
    all_specimens = list_specimen_names(specimens_base)

    # Collect all (bundle_url, ref) pairs from GitSource specimens
    for slug in all_specimens:
        manifest_path = specimens_base / slug / "manifest.yaml"
        rec, _ = SpecimenRegistry.load_lenient(slug, base=specimens_base)

        # Only process GitSource specimens (which have file:// bundle URLs)
        if not isinstance(rec.manifest.source, GitSource):
            continue

        # Resolve the bundle URL from the manifest's source
        bundle_url = _resolve_bundle_url(manifest_path, rec.manifest.source.url)

        # Only include file:// URLs (bundles are local files)
        if not bundle_url.startswith("file://"):
            continue

        # Only include refs/tags/* refs
        ref = rec.manifest.source.ref
        if ref.startswith("refs/tags/"):
            bundle_refs.append((bundle_url, ref))

    return sorted(bundle_refs, key=lambda x: (x[0], x[1]))


@pytest.fixture(scope="session")
def bare_repos_by_bundle(specimens_base: Path, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """Extract all bundles into temporary bare repositories.

    Returns a mapping from bundle URL to bare repo path.
    """
    bundle_refs = _find_bundle_and_refs(specimens_base)
    unique_bundles = {bundle_url for bundle_url, _ in bundle_refs}

    bare_repos = {}
    for bundle_url in unique_bundles:
        # Extract name from URL for temp dir naming
        bundle_name = Path(bundle_url.removeprefix("file://")).stem
        bare_dir = tmp_path_factory.mktemp(f"bare_{bundle_name}")

        # Initialize bare repository
        subprocess.run(["git", "init", "--bare"], cwd=bare_dir, check=True, capture_output=True)

        # Convert file:// URL to path for git fetch
        bundle_path = bundle_url.removeprefix("file://")

        # Fetch all refs from the bundle
        subprocess.run(["git", "fetch", bundle_path, "refs/*:refs/*"], cwd=bare_dir, check=True, capture_output=True)

        bare_repos[bundle_url] = bare_dir

    return bare_repos


def pytest_generate_tests(metafunc):
    """Dynamically parametrize tests with (bundle_url, ref) tuples."""
    if "bundle_and_ref" in metafunc.fixturenames:
        specimens_base = find_specimens_base()
        bundle_refs = _find_bundle_and_refs(specimens_base)
        # Create readable test IDs from URLs and refs
        ids = [f"{Path(url.removeprefix('file://')).parent.name}/{ref.split('/')[-1]}" for url, ref in bundle_refs]
        metafunc.parametrize("bundle_and_ref", bundle_refs, ids=ids)


def test_all_bundles_exist(specimens_base: Path) -> None:
    """Verify all bundle files exist."""
    bundle_refs = _find_bundle_and_refs(specimens_base)
    unique_bundles = {bundle_url for bundle_url, _ in bundle_refs}

    for bundle_url in unique_bundles:
        bundle_path = Path(bundle_url.removeprefix("file://"))
        assert bundle_path.exists(), f"Bundle not found at {bundle_path}"
        assert bundle_path.stat().st_size > 0, f"Bundle file is empty: {bundle_path}"


def test_bundle_has_expected_refs(bare_repos_by_bundle: dict[str, Path], specimens_base: Path) -> None:
    """Verify all expected specimen refs are in their bundles."""
    bundle_refs = _find_bundle_and_refs(specimens_base)

    # Group refs by bundle
    expected_by_bundle: dict[str, list[str]] = {}
    for bundle_url, ref in bundle_refs:
        if bundle_url not in expected_by_bundle:
            expected_by_bundle[bundle_url] = []
        expected_by_bundle[bundle_url].append(ref)

    # Check each bundle
    for bundle_url, expected_refs in expected_by_bundle.items():
        bare_dir = bare_repos_by_bundle[bundle_url]
        repo = pygit2.Repository(str(bare_dir))
        actual_refs = [ref for ref in repo.listall_references() if ref.startswith("refs/tags/")]

        bundle_name = Path(bundle_url.removeprefix("file://")).name
        assert sorted(actual_refs) == sorted(expected_refs), (
            f"Ref mismatch in {bundle_name}. Expected: {expected_refs}, Got: {actual_refs}"
        )


def test_bundle_excludes_libsonnet_files(
    bundle_and_ref: tuple[str, str], bare_repos_by_bundle: dict[str, Path], tmp_path: Path
) -> None:
    """Verify no .libsonnet files (specimen issues) are included in any commit.

    This test ensures that specimen bundles don't recursively include the specimen
    issue files themselves. The bundle should contain only the code snapshots, not
    the issue definitions that describe problems in those snapshots.
    """
    bundle_url, ref = bundle_and_ref
    bare_dir = bare_repos_by_bundle[bundle_url]

    # Clone and checkout using pygit2
    checkout_dir = tmp_path / "checkout"
    repo = pygit2.clone_repository(str(bare_dir), str(checkout_dir))

    # Checkout the ref (pygit2 handles full ref format)
    repo.set_head(ref)
    repo.checkout_head()

    # Find any .libsonnet files
    libsonnet_files = list(checkout_dir.rglob("*.libsonnet"))

    bundle_name = Path(bundle_url.removeprefix("file://")).name
    assert len(libsonnet_files) == 0, (
        f"Found {len(libsonnet_files)} .libsonnet files in {bundle_name}/{ref}:\n"
        + "\n".join(f"  - {f.relative_to(checkout_dir)}" for f in libsonnet_files[:10])
    )


def test_bundle_excludes_specimen_metadata(
    bundle_and_ref: tuple[str, str], bare_repos_by_bundle: dict[str, Path], tmp_path: Path
) -> None:
    """Verify no specimen metadata files (manifest.yaml, README.md in specimens/) are included.

    This ensures the specimens/ directory itself is not in the bundle.
    """
    bundle_url, ref = bundle_and_ref
    bare_dir = bare_repos_by_bundle[bundle_url]

    # Clone and checkout using pygit2
    checkout_dir = tmp_path / "checkout"
    repo = pygit2.clone_repository(str(bare_dir), str(checkout_dir))

    # Checkout the ref (pygit2 handles full ref format)
    repo.set_head(ref)
    repo.checkout_head()

    # Check for specimens directory
    specimens_dir = checkout_dir / "adgn" / "src" / "adgn" / "props" / "specimens"

    bundle_name = Path(bundle_url.removeprefix("file://")).name
    assert not specimens_dir.exists(), (
        f"specimens/ directory found in {bundle_name}/{ref}. "
        f"The bundle should exclude adgn/src/adgn/props/specimens/ to prevent recursive bundling."
    )
