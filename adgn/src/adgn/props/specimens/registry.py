from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from importlib import resources
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import time
from typing import TYPE_CHECKING, Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlunparse
from urllib.request import urlopen
import uuid

import _jsonnet  # type: ignore[import-untyped]
from filelock import FileLock
from platformdirs import user_cache_dir
from pydantic import BaseModel, ConfigDict
import yaml

from ..ids import FalsePositiveID, TruePositiveID
from ..models.issue import FalsePositiveOccurrence, IssueCore, IssueOccurrence, SpecimenIssuesLoadError
from ..models.specimen import GitHubSource, GitSource, LocalSource, SpecimenDoc
from ..paths import FileType, classify_path
from ..rationale import Rationale
from ..splits import Split
from ..validation_context import SpecimenContext

if TYPE_CHECKING:
    # Import for type annotations only to avoid circular dependency
    from .hydrated import HydratedSpecimen

logger = logging.getLogger(__name__)


def _make_unique_temp_path(parent: Path, suffix: str = ".tar.gz") -> Path:
    """Create a unique temporary file path to avoid conflicts in parallel execution."""
    return parent / f".tmp-{uuid.uuid4().hex}{suffix}"


def _specimen_extract_filter(member: tarfile.TarInfo, path: str) -> tarfile.TarInfo | None:
    """Custom tarfile extraction filter for specimens.

    Based on tarfile.data_filter but skips absolute symlinks instead of raising error.
    Specimens are read-only training data from known commits, so absolute symlinks
    (while discouraged) don't pose a security risk here.
    """
    # Use data_filter as base, but catch AbsoluteLinkError
    try:
        return tarfile.data_filter(member, path)
    except tarfile.AbsoluteLinkError:
        # Skip absolute symlinks with warning
        logger.warning(f"Skipping absolute symlink in specimen: {member.name} -> {member.linkname}")
        return None


# TODO: Consider generic Issue[IDType] to reduce duplication between these models
class CanonicalIssue(BaseModel):
    """Canonical true positive issue with typed namespaced ID."""

    id: TruePositiveID
    rationale: Rationale
    occurrences: list[Occurrence]

    model_config = ConfigDict(frozen=True)


class KnownFalsePositive(BaseModel):
    """Known false positive issue with typed namespaced ID."""

    id: FalsePositiveID
    rationale: Rationale
    occurrences: list[Occurrence]

    model_config = ConfigDict(frozen=True)


@dataclass(frozen=True)
class IssueRecord:
    core: IssueCore
    instances: list[IssueOccurrence | FalsePositiveOccurrence]


@dataclass(frozen=True)
class IssuesLoadResult:
    items: list[IssueRecord]
    errors: list[str]


# ---- Shared Jsonnet loader helpers ----
JSONNET_LIBDIR = Path(__file__).resolve().parent


def _jsonnet_importer(base: str, rel: str) -> tuple[str, bytes]:
    cand1 = (Path(base) / rel).resolve()
    if cand1.is_file():
        return str(cand1), cand1.read_bytes()
    rel_name = Path(rel).name
    cand2 = (JSONNET_LIBDIR / rel_name).resolve()
    if cand2.is_file():
        return str(cand2), cand2.read_bytes()
    raise RuntimeError(f"import not found: base={base!r} rel={rel!r}")


def _jsonnet_evaluate_all(spec_dir: Path) -> tuple[dict[str, dict], dict[str, dict]] | None:
    """Evaluate all Jsonnet files in specimen directory and split by type.

    All libsonnet files are directly in specimen directory.
    TPs and FPs are distinguished by content (expect_caught_from vs relevant_files).

    Args:
        spec_dir: Specimen directory containing libsonnet files

    Returns:
        Tuple of (true_positives, false_positives) dicts, or None if no files found.
        Each dict maps issue_id -> raw dict (with id and should_flag injected).
    """
    if not spec_dir.is_dir():
        return None

    # Discover all libsonnet files in the directory
    issue_files = sorted(spec_dir.glob("*.libsonnet"))
    if not issue_files:
        return None

    # Build Jsonnet snippet to batch-load all files (without should_flag yet)
    imports = []
    for p in issue_files:
        name = p.stem
        abs_path = str(p.resolve())
        imports.append(f"  {json.dumps(name)}: (import {json.dumps(abs_path)}) + {{id: {json.dumps(name)}}}")

    snippet = "{\n" + ",\n".join(imports) + "\n}"

    eval_snippet = cast(Callable[..., Any], _jsonnet.evaluate_snippet)
    raw_obj = eval_snippet(
        "<batch:flat>", snippet, jpathdir=[str(JSONNET_LIBDIR)], import_callback=_jsonnet_importer
    )
    if not isinstance(raw_obj, str):
        raise SpecimenIssuesLoadError(["flat: Jsonnet returned non-string"])

    all_issues = json.loads(raw_obj)
    if not isinstance(all_issues, dict):
        raise SpecimenIssuesLoadError([f"flat: Expected dict, got {type(all_issues)}"])

    # Split into TPs and FPs based on occurrence structure
    true_positives: dict[str, dict] = {}
    false_positives: dict[str, dict] = {}

    for issue_id, issue_dict in all_issues.items():
        if not isinstance(issue_dict, dict):
            continue

        occurrences = issue_dict.get("occurrences", [])
        if not occurrences:
            continue

        # Check first occurrence to determine type
        first_occ = occurrences[0]
        is_tp = "expect_caught_from" in first_occ
        is_fp = "relevant_files" in first_occ

        if is_tp:
            issue_dict["should_flag"] = True
            true_positives[issue_id] = issue_dict
        elif is_fp:
            issue_dict["should_flag"] = False
            false_positives[issue_id] = issue_dict
        # Skip issues that don't have either field (malformed)

    return true_positives, false_positives


def _validate_issues_from_dicts(
    raw_issues: dict[str, dict],
    validation_context: dict,
    strict: bool,
    *,
    is_true_positive: bool = True,
) -> IssuesLoadResult:
    """Validate pre-evaluated issue dicts with complete context.

    Args:
        raw_issues: Dict mapping issue_id -> raw dict (from Jsonnet evaluation)
        validation_context: Complete validation context (specimen_context with files + IDs)
        strict: If True, raise on any validation errors
        is_true_positive: If True, validate as IssueOccurrence; if False, as FalsePositiveOccurrence

    Returns:
        IssuesLoadResult with validated items and errors
    """
    items: list[IssueRecord] = []
    errors: list[str] = []

    # Select occurrence model based on type
    occurrence_model = IssueOccurrence if is_true_positive else FalsePositiveOccurrence

    for issue_id, issue_dict in raw_issues.items():
        if not isinstance(issue_dict, dict):
            errors.append(f"{issue_id}: Not a dict (got {type(issue_dict)})")
            continue

        try:
            # IssueCore validation (strip non-core fields)
            non_core_fields = {"instances", "occurrences", "should_flag"}
            core_fields = {k: v for k, v in issue_dict.items() if k not in non_core_fields}
            core = IssueCore.model_validate(core_fields, context=validation_context)
            # Occurrences may be named "instances" or "occurrences" depending on source
            inst_raw = issue_dict.get("instances") or issue_dict.get("occurrences", [])
            instances = [occurrence_model.model_validate(inst, context=validation_context) for inst in inst_raw]
            items.append(IssueRecord(core=core, instances=instances))
        except Exception as e:
            errors.append(f"{issue_id}: {e}")
            continue

    if errors and strict:
        raise SpecimenIssuesLoadError(errors)
    return IssuesLoadResult(items=items, errors=errors)


def _xdg_cache_base() -> Path:
    # Prefer shared cache dir alongside existing helpers

    root = Path(user_cache_dir(appname="adgn-llm", appauthor=False)) / "specimens"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _extract_tar_gz_to_temp(archive: Path) -> Path:
    tmpdir = Path(tempfile.mkdtemp(prefix="adgn-specimen-extract-"))
    with tarfile.open(archive, "r:gz") as tf:
        tf.extractall(tmpdir, filter=_specimen_extract_filter)
    for p in tmpdir.iterdir():
        if p.is_dir():
            return p.resolve()
    return tmpdir


def _repack_dir_with_mtime(src_dir: Path, out_archive: Path, mtime: int = 0) -> None:
    out_archive.parent.mkdir(parents=True, exist_ok=True)

    def _filter(ti: tarfile.TarInfo) -> tarfile.TarInfo | None:
        # Exclude VCS internals from archives to avoid permission issues and reduce size
        # Skip any member whose path includes a '.git' segment
        parts = ti.name.split("/")
        if ".git" in parts:
            return None
        ti.mtime = int(mtime)
        # Preserve uid/gid; determinism here only requires pinned mtime
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
    extracted = _extract_tar_gz_to_temp(archive)
    _repack_dir_with_mtime(extracted, archive, mtime=mtime)
    shutil.rmtree(extracted, ignore_errors=True)
    return archive


def _download_github_to(owner: str, repo: str, ref: str, dest: Path) -> bool:
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
    tmpdir = Path(tempfile.mkdtemp(prefix="adgn-specimen-git-"))

    try:
        # Check if URL points to a bundle file
        if url.startswith("file://"):
            file_path = url.removeprefix("file://")
            if file_path.endswith(".bundle"):
                # For bundles, use subprocess since pygit2 doesn't handle bundles well
                # Clone from bundle using subprocess
                subprocess.run(
                    ["git", "clone", file_path, str(tmpdir)],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                subprocess.run(["git", "-C", str(tmpdir), "checkout", "--detach", ref], check=True)
            else:
                # Regular file:// repository - use standard approach with subprocess
                # (pygit2 has issues with file:// URLs)
                subprocess.run(["git", "init", str(tmpdir)], check=True, stdout=subprocess.DEVNULL)
                subprocess.run(["git", "-C", str(tmpdir), "remote", "add", "origin", url], check=True)
                subprocess.run(["git", "-C", str(tmpdir), "fetch", "--depth", "1", "origin", ref], check=True)
                subprocess.run(["git", "-C", str(tmpdir), "checkout", "--detach", ref], check=True)
        else:
            # For non-file URLs, fall back to subprocess for now
            # (pygit2 network operations can be complex with auth)
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


def ensure_archive_for_specimen_slug(man: SpecimenDoc, specimen_path: Path) -> Path:
    """Ensure a cached archive exists for the specimen.

    The slug is computed from the specimen path as repo/name.
    For GitSource with commit SHA: ~/.cache/adgn-llm/specimens/{repo}/{name}-{commit}.tar.gz
    Otherwise: ~/.cache/adgn-llm/specimens/{repo}/{name}.tar.gz

    Uses a lock file to prevent concurrent cache creation from multiple processes.
    """
    # Extract hierarchical slug from path: specimens/{repo}/{name}/_specimen -> repo/name
    specimen_dir = specimen_path.parent
    repo_name = specimen_dir.parent.name
    specimen_name = specimen_dir.name
    slug = f"{repo_name}/{specimen_name}"

    # Include commit SHA in cache key for GitSource to avoid staleness
    cache_filename = specimen_name
    if isinstance(man.source, GitSource) and man.source.commit:
        cache_filename = f"{specimen_name}-{man.source.commit}"

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

        if isinstance(man.source, GitHubSource):
            if _download_github_to(man.source.org, man.source.repo, man.source.ref, out):
                _repack_tar_with_mtime(out, mtime=0)
                return out
            if (
                _create_archive_from_git(
                    urlunparse(("https", "github.com", f"/{man.source.org}/{man.source.repo}.git", "", "", "")),
                    man.source.ref,
                    out,
                )
                and out.exists()
            ):
                return out
        elif isinstance(man.source, GitSource):
            # Prefer commit SHA for exact fetching; ref is optional and may have moved
            git_ref = man.source.commit

            if man.source.url.startswith("https://github.com/"):
                parts = man.source.url.removeprefix("https://github.com/").rstrip("/").removesuffix(".git").split("/")
                if len(parts) >= 2 and _download_github_to(parts[0], parts[1], git_ref, out):
                    _repack_tar_with_mtime(out, mtime=0)
                    return out
            # Resolve relative file:// URLs relative to the specimen directory
            url = resolve_bundle_url(specimen_path, man.source.url)

            if _create_archive_from_git(url, git_ref, out) and out.exists():
                return out
        elif isinstance(man.source, LocalSource):
            src = (specimen_path.parent / man.source.root).resolve()
            _repack_dir_with_mtime(src, out, mtime=0)
            return out
        raise SystemExit(f"Can't archive specimen cache for '{slug}' (source={type(man.source).__name__}); ")


def resolve_bundle_url(specimen_path: Path, source_url: str) -> str:
    """Resolve bundle URL, handling relative file:// paths.

    Args:
        specimen_path: Path inside specimen directory (for relative URL resolution)
        source_url: Source URL from specimen (may be relative file://)

    Returns:
        Absolute URL (file:// URLs are resolved relative to specimen directory)
    """
    url = source_url
    if url.startswith("file://"):
        file_path = url.removeprefix("file://")
        if not file_path.startswith("/"):
            resolved_path = (specimen_path.parent / file_path).resolve()
            url = f"file://{resolved_path}"
    return url


def resolve_source_root(man: SpecimenDoc, specimen_path: Path) -> Path:
    if isinstance(man.source, GitHubSource | GitSource):
        archive = ensure_archive_for_specimen_slug(man, specimen_path)
        return _extract_tar_gz_to_temp(archive)
    if isinstance(man.source, LocalSource):
        # Use existing local copy helper for consistency
        src = (specimen_path.parent / man.source.root).resolve()
        tmpdir = Path(tempfile.mkdtemp(prefix="adgn-specimen-local-"))
        dest = tmpdir / src.name
        shutil.copytree(src, dest)
        return dest
    raise SystemExit(f"Unsupported source type: {type(man.source)}")


@dataclass(frozen=True)
class SpecimenRecord:
    slug: str
    specimen_path: Path  # Synthetic path to specimen directory (for URL resolution)
    manifest: SpecimenDoc
    issues: dict[str, IssueRecord]
    false_positives: dict[str, IssueRecord]
    all_discovered_files: dict[Path, FileType]  # File map from hydration (for complete validation contexts)

    @asynccontextmanager
    async def hydrated_copy(self) -> AsyncIterator[Path]:
        """Yield a fresh private working tree path under $HOME for Docker-friendly mounts; clean up on exit.

        On macOS/Docker Desktop, mounts must be under $HOME to be shared with the VM. We therefore extract/copy under
        ~/.cache/adgn-llm/workspaces/<slug>_<ts>/ and yield the single extracted top-level directory.
        """
        # Build a Docker-friendly mount root under $HOME
        mount_base = Path.home() / ".cache" / "adgn-llm" / "workspaces"
        mount_base.mkdir(parents=True, exist_ok=True)
        mount_root = mount_base / f"{self.slug}_{int(time.time())}"
        if mount_root.exists():
            shutil.rmtree(mount_root, ignore_errors=True)
        mount_root.mkdir(parents=True, exist_ok=True)

        # Materialize contents into mount_root according to source
        try:
            if isinstance(self.manifest.source, GitHubSource | GitSource):
                archive = ensure_archive_for_specimen_slug(self.manifest, self.specimen_path)
                with tarfile.open(archive, "r:gz") as tf:
                    members = [m for m in tf.getmembers() if ".git" not in m.name.split("/")]
                    if os.environ.get("ADGN_DEBUG_SPECIMEN") == "1":
                        total = len(tf.getmembers())
                        filtered = len(members)
                        logger.debug("[specimen] extracting %s members=%s/%s (filtered .git)", archive, filtered, total)
                    tf.extractall(mount_root, members=members, filter=_specimen_extract_filter)
                    if os.environ.get("ADGN_DEBUG_SPECIMEN") == "1":
                        git_dirs = list((mount_root).rglob(".git"))
                        logger.debug("[specimen] post-extract .git dirs: %d", len(git_dirs))
                        for p in git_dirs[:10]:
                            logger.debug("    %s", p)
            elif isinstance(self.manifest.source, LocalSource):
                src = (self.specimen_path.parent / self.manifest.source.root).resolve()
                # For local specimens, materialize directly into mount_root (no extra subdir)
                shutil.copytree(src, mount_root, dirs_exist_ok=True)
            else:  # pragma: no cover - guarded by SpecimenDoc model
                raise SystemExit(f"Unsupported source type: {type(self.manifest.source)}")

            # Determine content root:
            # - If exactly one directory and no files: use that directory (typical for tarball extractions)
            # - Otherwise (e.g., local specimens copied directly): use mount_root itself
            all_entries = list(mount_root.iterdir())
            dirs = [p for p in all_entries if p.is_dir()]
            files = [p for p in all_entries if p.is_file()]
            content_root = dirs[0] if (len(dirs) == 1 and not files) else mount_root
            yield content_root
        finally:
            shutil.rmtree(mount_root, ignore_errors=True)

    @property
    def canonical_issues(self) -> list[CanonicalIssue]:
        """Canonical true positive issues with typed namespaced IDs."""
        return [
            CanonicalIssue(
                id=TruePositiveID(record.core.id), rationale=record.core.rationale, occurrences=record.instances
            )
            for record in self.issues.values()
        ]

    @property
    def known_false_positives(self) -> list[KnownFalsePositive]:
        """Known false positive issues with typed namespaced IDs."""
        return [
            KnownFalsePositive(
                id=FalsePositiveID(record.core.id), rationale=record.core.rationale, occurrences=record.instances
            )
            for record in self.false_positives.values()
        ]


class SpecimenRegistry:
    """Entry point for listing and obtaining specimen records (code-only facade).

    DI-friendly: pass in a preloaded mapping for tests; use from_base_path() factory in app code.

    Specimens are defined in snapshots.yaml at the specimens directory root.
    """

    def __init__(
        self,
        specimens: dict[str, SpecimenRecord | None],
        base_path: Path,
        manifests: dict[str, SpecimenDoc],
    ) -> None:
        # No I/O here; accept fully materialized data
        self._specimens = specimens
        self._base_path = base_path
        self._manifests = manifests

    @classmethod
    def from_base_path(cls, base: Path) -> SpecimenRegistry:
        """Factory method to create a registry from a specific base directory.

        Args:
            base: Specimens base directory (must contain snapshots.yaml)

        Returns:
            SpecimenRegistry instance

        Raises:
            FileNotFoundError: If snapshots.yaml doesn't exist
        """
        snapshots_yaml = base / "snapshots.yaml"
        if not snapshots_yaml.exists():
            raise FileNotFoundError(f"snapshots.yaml not found at {snapshots_yaml}")

        specimens: dict[str, SpecimenRecord | None] = {}
        manifests: dict[str, SpecimenDoc] = {}

        raw = yaml.safe_load(snapshots_yaml.read_text(encoding="utf-8")) or {}
        for slug, data in raw.items():
            specimens[slug] = None
            manifests[slug] = SpecimenDoc.model_validate(data)

        return cls(specimens=specimens, base_path=base, manifests=manifests)

    @classmethod
    def from_package_resources(cls) -> SpecimenRegistry:
        """Factory method to create a registry from package resources.

        Returns:
            SpecimenRegistry instance with specimens from package resources
        """
        # Resolve from package resources
        traversable = resources.files("adgn.props").joinpath("specimens")
        with resources.as_file(traversable) as p:
            if not p.exists() or not p.is_dir():
                raise FileNotFoundError(f"Specimens directory not found in package resources: {p}")
            return cls.from_base_path(base=p)

    @property
    def base_path(self) -> Path:
        """Base directory where specimens are located."""
        return self._base_path

    @property
    def specimen_ids(self) -> list[str]:
        """List of specimen slugs in this registry."""
        return sorted(self._specimens.keys())

    def _get_specimen_path(self, slug: str) -> Path:
        """Get specimen directory path for a slug.

        Returns a synthetic path used for bundle URL resolution. The path points
        to a synthetic file inside the specimen directory to maintain consistent
        resolution behavior for relative URLs.

        Args:
            slug: Specimen slug like "ducktape/2025-11-20-00"

        Returns:
            Resolved absolute path inside specimen directory (for URL resolution)
        """
        return (self._base_path / slug.replace("/", os.sep) / "_specimen").resolve()

    @asynccontextmanager
    async def load_and_hydrate(self, slug: str) -> AsyncIterator[HydratedSpecimen]:
        """Load specimen with validation and yield hydrated specimen object.

        Avoids double-hydration when caller needs both loaded issues and hydrated specimen.

        Args:
            slug: Specimen slug like "ducktape/2025-11-20-00"

        Yields:
            HydratedSpecimen: Single object containing specimen record + hydrated content root

        Example:
            registry = SpecimenRegistry.from_base_path()
            async with registry.load_and_hydrate("ducktape/2025-11-20-00") as hydrated:
                # Access specimen data: hydrated.all_discovered_files, hydrated.issues
                # Access content root: hydrated.content_root
                pass
        """
        specimen_path = self._get_specimen_path(slug)
        man = self._manifests[slug]

        # Determine specimen directory for issue loading
        specimen_dir = specimen_path.parent

        # Evaluate Jsonnet to raw dicts (no validation yet)
        result = _jsonnet_evaluate_all(specimen_dir)
        if result is None:
            raise SpecimenIssuesLoadError([f"No issues found under: {specimen_dir}"])
        raw_issues, raw_fps = result

        # Hydrate specimen to build complete validation context
        hydrated_root = resolve_source_root(man, specimen_path)
        try:
            # Build complete context: files from hydration + IDs from Jsonnet
            all_discovered_files = {p.relative_to(hydrated_root): classify_path(p) for p in hydrated_root.rglob("*")}
            ctx = SpecimenContext(
                specimen_slug=slug,
                all_discovered_files=all_discovered_files,
                allowed_tp_ids=list(raw_issues.keys()),  # IDs from Jsonnet (strings)
                allowed_fp_ids=list(raw_fps.keys()),  # IDs from Jsonnet (strings)
            )
            context_dict = {"specimen_context": ctx}

            # Validate with complete context (both paths and IDs)
            res_pos = _validate_issues_from_dicts(raw_issues, context_dict, strict=True, is_true_positive=True)
            res_fp = _validate_issues_from_dicts(raw_fps, context_dict, strict=True, is_true_positive=False)

            if res_pos.errors or res_fp.errors:
                raise SpecimenIssuesLoadError([*res_pos.errors, *res_fp.errors])

            # Create record with stored file map
            rec = SpecimenRecord(
                slug=slug,
                specimen_path=specimen_path,
                manifest=man,
                issues={it.core.id: it for it in res_pos.items},
                false_positives={it.core.id: it for it in res_fp.items},
                all_discovered_files=all_discovered_files,  # Store for complete validation contexts
            )

            # Runtime import to avoid circular dependency (type annotation uses TYPE_CHECKING)
            from adgn.props.specimens.hydrated import HydratedSpecimen  # noqa: PLC0415

            # Yield hydrated specimen - single object with record + content root
            yield HydratedSpecimen(record=rec, content_root=hydrated_root)
        finally:
            # Clean up hydrated specimen
            shutil.rmtree(
                hydrated_root.parent if hydrated_root.parent.name.startswith("adgn-specimen-") else hydrated_root,
                ignore_errors=True,
            )

    def load_manifest_only(self, slug: str) -> tuple[Path, SpecimenDoc]:
        """Load only the manifest (no Jsonnet issues) for fast collection.

        Args:
            slug: Specimen slug like "ducktape/2025-11-20-00"

        Returns:
            Tuple of (specimen_path, manifest_doc)
        """
        specimen_path = self._get_specimen_path(slug)
        return (specimen_path, self._manifests[slug])

    def list_all(self) -> set[str]:
        """List all specimen names in hierarchical format (repo/name).

        Returns specimen IDs like "ducktape/2025-11-20-adgn", "crush/2025-08-30-internal_db"

        Returns:
            Set of specimen IDs in format "repo/name"
        """
        return set(self._specimens.keys())

    def get_split(self, slug: str) -> Split:
        """Get the train/valid/test split for a specimen from its manifest.

        Args:
            slug: Specimen identifier (e.g., "ducktape/2025-11-20-00")

        Returns:
            Split.TRAIN, Split.VALID, or Split.TEST

        Raises:
            FileNotFoundError: If specimen manifest doesn't exist
            ValidationError: If manifest is malformed or missing split field
        """
        _, manifest = self.load_manifest_only(slug)
        return manifest.split

    def get_specimens_by_split(self, split: Split) -> list[str]:
        """Get all specimen slugs for a given split.

        Args:
            split: The split to filter by (TRAIN, VALID, or TEST)

        Returns:
            List of specimen slugs in the given split, sorted alphabetically
        """
        result = []
        for slug in sorted(self._specimens.keys()):
            _, manifest = self.load_manifest_only(slug)
            if manifest.split == split:
                result.append(slug)
        return result
