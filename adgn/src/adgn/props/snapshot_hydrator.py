"""Source code hydration for snapshots (no issue loading).

SnapshotHydrator extracts snapshot source code to temporary directories.
Issues must be loaded separately from database via ORM Snapshot model.

This is the public API for runtime components (grader, critic, GEPA, CLI).
For sync operations, use db.sync.SyncLoader (private).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import urlunparse
from urllib.request import urlopen

from filelock import FileLock
from platformdirs import user_cache_dir
import yaml

from .ids import SnapshotSlug, get_snapshot_manifest_path
from .models.snapshot import GitHubSource, GitSource, LocalSource, SnapshotDoc
from .paths import classify_path
from .prop_utils import specimens_definitions_root
from .snapshot_hydrated import HydratedSnapshot

logger = logging.getLogger(__name__)


# ========== Source Hydration Helpers ==========
# These functions handle extracting source code from various sources
# (GitHub, Git repos, local directories). No issue processing.


def _specimen_extract_filter(member: tarfile.TarInfo, path: str) -> tarfile.TarInfo | None:
    """Custom tarfile extraction filter for specimens.

    Based on tarfile.data_filter but skips absolute symlinks instead of raising error.
    Specimens are read-only training data from known commits, so absolute symlinks
    (while discouraged) don't pose a security risk here.
    """
    try:
        return tarfile.data_filter(member, path)
    except tarfile.AbsoluteLinkError:
        logger.warning(f"Skipping absolute symlink in specimen: {member.name} -> {member.linkname}")
        return None


def _xdg_cache_base() -> Path:
    """Get cache directory for specimen archives."""
    root = Path(user_cache_dir(appname="adgn-llm", appauthor=False)) / "snapshots"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _extract_tar_gz_to_temp(archive: Path) -> Path:
    """Extract tar.gz archive to temporary directory and return extracted root."""
    tmpdir = Path(tempfile.mkdtemp(prefix="adgn-snapshot-extract-"))
    with tarfile.open(archive, "r:gz") as tf:
        tf.extractall(tmpdir, filter=_specimen_extract_filter)
    # Return the single top-level directory if it exists
    for p in tmpdir.iterdir():
        if p.is_dir():
            return p.resolve()
    return tmpdir


def _make_unique_temp_path(parent: Path) -> Path:
    """Create unique temp file path (doesn't create the file)."""
    return parent / f".tmp.{tempfile.mktemp(dir='')}"


def _repack_dir_with_mtime(src_dir: Path, out_archive: Path, mtime: int = 0) -> None:
    """Repack directory as tar.gz with deterministic mtime."""
    out_archive.parent.mkdir(parents=True, exist_ok=True)

    def _filter(ti: tarfile.TarInfo) -> tarfile.TarInfo | None:
        # Exclude VCS internals from archives to avoid permission issues and reduce size
        parts = ti.name.split("/")
        if ".git" in parts:
            return None
        ti.mtime = int(mtime)
        return ti

    tmp = _make_unique_temp_path(out_archive.parent)
    logger.debug("repacking %s -> %s (via %s, filter .git, mtime=%s)", src_dir, out_archive, tmp.name, mtime)

    try:
        with tarfile.open(tmp, "w:gz", format=tarfile.PAX_FORMAT) as tf:
            tf.add(src_dir, arcname=Path(src_dir).name, filter=_filter)
        logger.debug("repack complete, renaming %s -> %s", tmp.name, out_archive.name)
        tmp.replace(out_archive)
    except Exception:
        logger.debug("repack failed, cleaning up %s", tmp.name)
        if tmp.exists():
            tmp.unlink()
        raise


def _repack_tar_with_mtime(archive: Path, mtime: int = 0) -> Path:
    """Repack existing tar.gz with deterministic mtime."""
    extracted = _extract_tar_gz_to_temp(archive)
    _repack_dir_with_mtime(extracted, archive, mtime=mtime)
    shutil.rmtree(extracted, ignore_errors=True)
    return archive


def _download_github_to(owner: str, repo: str, ref: str, dest: Path) -> bool:
    """Download GitHub tarball to dest. Returns True on success."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = urlunparse(("https", "codeload.github.com", f"/{owner}/{repo}/tar.gz/{ref}", "", "", ""))
    tmp = _make_unique_temp_path(dest.parent)
    logger.debug("downloading %s -> %s (via %s)", url, dest, tmp.name)

    try:
        with urlopen(url) as resp:
            tmp.write_bytes(resp.read())
        logger.debug("download complete, renaming %s -> %s", tmp.name, dest.name)
        tmp.replace(dest)
        return True
    except (URLError, HTTPError) as e:
        logger.debug("download failed (%s), cleaning up %s", e, tmp.name)
        if tmp.exists():
            tmp.unlink()
        return False


def _create_archive_from_git(url: str, ref: str, out_archive: Path) -> bool:
    """Create archive from git URL. Returns True on success."""
    tmpdir = Path(tempfile.mkdtemp(prefix="adgn-snapshot-git-"))

    try:
        # Handle bundle files
        if url.startswith("file://"):
            file_path = url.removeprefix("file://")
            if file_path.endswith(".bundle"):
                subprocess.run(
                    ["git", "clone", file_path, str(tmpdir)],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                subprocess.run(["git", "-C", str(tmpdir), "checkout", "--detach", ref], check=True)
            else:
                # Regular file:// repository
                subprocess.run(["git", "init", str(tmpdir)], check=True, stdout=subprocess.DEVNULL)
                subprocess.run(["git", "-C", str(tmpdir), "remote", "add", "origin", url], check=True)
                subprocess.run(["git", "-C", str(tmpdir), "fetch", "--depth", "1", "origin", ref], check=True)
                subprocess.run(["git", "-C", str(tmpdir), "checkout", "--detach", ref], check=True)
        else:
            # For non-file URLs, use git commands
            subprocess.run(["git", "init", str(tmpdir)], check=True, stdout=subprocess.DEVNULL)
            subprocess.run(["git", "-C", str(tmpdir), "remote", "add", "origin", url], check=True)
            subprocess.run(["git", "-C", str(tmpdir), "fetch", "--depth", "1", "origin", ref], check=True)
            subprocess.run(["git", "-C", str(tmpdir), "checkout", "--detach", ref], check=True)

        # Drop VCS internals to keep archives small and writable on extract
        shutil.rmtree(tmpdir / ".git", ignore_errors=True)
        _repack_dir_with_mtime(tmpdir, out_archive, mtime=0)
        return True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def resolve_bundle_url(snapshot_path: Path, source_url: str) -> str:
    """Resolve bundle URL, handling relative file:// paths."""
    url = source_url
    if url.startswith("file://"):
        file_path = url.removeprefix("file://")
        if not file_path.startswith("/"):
            resolved_path = (snapshot_path.parent / file_path).resolve()
            url = f"file://{resolved_path}"
    return url


def ensure_archive_for_snapshot(manifest: SnapshotDoc, snapshot_path: Path) -> Path:
    """Ensure a cached archive exists for the snapshot.

    The slug is computed from the snapshot path as repo/name.
    For GitSource with commit SHA: ~/.cache/adgn-llm/snapshots/{repo}/{name}-{commit}.tar.gz
    Otherwise: ~/.cache/adgn-llm/snapshots/{repo}/{name}.tar.gz

    Uses a lock file to prevent concurrent cache creation from multiple processes.
    """
    # Extract hierarchical slug from path: specimens/{repo}/{name}/_snapshot -> repo/name
    snapshot_dir = snapshot_path.parent
    repo_name = snapshot_dir.parent.name
    snapshot_name = snapshot_dir.name
    slug = f"{repo_name}/{snapshot_name}"

    # Include commit SHA in cache key for GitSource to avoid staleness
    cache_filename = snapshot_name
    if isinstance(manifest.source, GitSource) and manifest.source.commit:
        cache_filename = f"{snapshot_name}-{manifest.source.commit}"

    # Cache hierarchically
    out = _xdg_cache_base() / repo_name / f"{cache_filename}.tar.gz"
    lock_file = out.with_suffix(".lock")

    logger.debug("ensure_archive slug=%s out=%s", slug, out.name)

    # Fast path: if archive already exists, return it without acquiring lock
    if out.exists():
        logger.debug("archive exists (fast path), returning %s", out.name)
        return out

    logger.debug("archive missing, acquiring lock %s", lock_file.name)
    # Acquire lock to prevent concurrent cache creation
    with FileLock(lock_file):
        logger.debug("lock acquired, checking if archive was created while waiting")
        # Check again after acquiring lock (another process may have created it)
        if out.exists():
            logger.debug("archive exists (created while waiting), returning %s", out.name)
            return out

        logger.debug("archive still missing, creating it")

        if isinstance(manifest.source, GitHubSource):
            if _download_github_to(manifest.source.org, manifest.source.repo, manifest.source.ref, out):
                _repack_tar_with_mtime(out, mtime=0)
                return out
            # Fallback to git clone
            if (
                _create_archive_from_git(
                    urlunparse(
                        ("https", "github.com", f"/{manifest.source.org}/{manifest.source.repo}.git", "", "", "")
                    ),
                    manifest.source.ref,
                    out,
                )
                and out.exists()
            ):
                return out
        elif isinstance(manifest.source, GitSource):
            # Prefer commit SHA for exact fetching
            git_ref = manifest.source.commit

            # Try GitHub fast path for github.com URLs
            if manifest.source.url.startswith("https://github.com/"):
                parts = (
                    manifest.source.url.removeprefix("https://github.com/").rstrip("/").removesuffix(".git").split("/")
                )
                if len(parts) >= 2 and _download_github_to(parts[0], parts[1], git_ref, out):
                    _repack_tar_with_mtime(out, mtime=0)
                    return out

            # Resolve relative file:// URLs relative to the snapshot directory
            url = resolve_bundle_url(snapshot_path, manifest.source.url)

            if _create_archive_from_git(url, git_ref, out) and out.exists():
                return out
        elif isinstance(manifest.source, LocalSource):
            src = (snapshot_path.parent / manifest.source.root).resolve()
            _repack_dir_with_mtime(src, out, mtime=0)
            return out

        raise SystemExit(f"Can't archive snapshot cache for '{slug}' (source={type(manifest.source).__name__})")


def resolve_source_root(manifest: SnapshotDoc, snapshot_path: Path) -> Path:
    """Extract/copy snapshot source to temporary directory (with caching for Git sources).

    Args:
        manifest: Snapshot manifest (source type determines extraction method)
        snapshot_path: Path to snapshot's _snapshot file (for relative URL resolution)

    Returns:
        Path to extracted source code root (temporary directory)
    """
    if isinstance(manifest.source, GitHubSource | GitSource):
        archive = ensure_archive_for_snapshot(manifest, snapshot_path)
        return _extract_tar_gz_to_temp(archive)
    if isinstance(manifest.source, LocalSource):
        # Copy local source to temp directory
        src = (snapshot_path.parent / manifest.source.root).resolve()
        tmpdir = Path(tempfile.mkdtemp(prefix="adgn-snapshot-local-"))
        dest = tmpdir / src.name
        shutil.copytree(src, dest)
        return dest
    raise SystemExit(f"Unsupported source type: {type(manifest.source)}")


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
        return get_snapshot_manifest_path(self._base_path, slug)

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
