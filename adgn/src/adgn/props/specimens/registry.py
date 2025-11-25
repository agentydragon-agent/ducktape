from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from importlib import resources
import json
import os
import logging
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
from urllib.parse import urlunparse

import _jsonnet
from platformdirs import user_cache_dir
import pygit2
import yaml
from typing import Any, Callable, cast

from ..models.issue import IssueCore, Occurrence, SpecimenIssuesLoadError
from ..models.specimen import GitHubSource, GitSource, LocalSource, SpecimenDoc
from ..prop_utils import pkg_dir

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class IssueRecord:
    core: IssueCore
    instances: list[Occurrence]


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


def _jsonnet_load_dir(
    spec_dir: Path,
    subdir: str,
    should_flag: bool,
    *,
    strict: bool = True,
    allow_missing: bool = False,
) -> IssuesLoadResult:
    dir_path = spec_dir / subdir
    items: list[IssueRecord] = []
    errors: list[str] = []
    if not dir_path.is_dir():
        if allow_missing:
            return IssuesLoadResult(items=items, errors=errors)
        raise SpecimenIssuesLoadError(
            [f"No {subdir}/ directory found under: {spec_dir}"],
        )

    for p in sorted(dir_path.glob("*.libsonnet")):
        stem = p.stem
        try:
            # NOTE: _jsonnet type stubs omit jpathdir/import_callback; runtime supports them.
            eval_file = cast(Callable[..., Any], _jsonnet.evaluate_file)
            raw_obj = eval_file(
                str(p),
                jpathdir=[str(JSONNET_LIBDIR)],
                import_callback=_jsonnet_importer,
            )
        except Exception as e:  # pragma: no cover
            errors.append(f"{p}: Jsonnet evaluation error: {e}")
            continue
        if not isinstance(raw_obj, str):
            errors.append(
                f"{p}: Jsonnet evaluator returned non-string (expected JSON text)",
            )
            continue
        raw = raw_obj
        try:
            obj = json.loads(raw)
        except Exception as e:
            errors.append(f"{p}: Failed to parse Jsonnet output as JSON: {e}")
            continue
        if not isinstance(obj, dict):
            errors.append(f"{p}: Jsonnet did not produce an object (got {type(obj)})")
            continue
        if "id" in obj:
            errors.append(
                f"{p}: Embedded IDs no longer accepted, IDs are always derived from path - remove 'id' from jsonnet",
            )
            continue
        try:
            core_input = {k: obj.get(k) for k in ("rationale", "gap_note")}
            core_input["id"] = stem
            core_input["should_flag"] = should_flag
            core = IssueCore.model_validate(core_input)
            inst_raw = obj.get("instances")
            if inst_raw is None:
                inst_raw = []
            instances = [Occurrence.model_validate(inst) for inst in inst_raw]
            items.append(IssueRecord(core=core, instances=instances))
        except Exception as e:
            errors.append(f"{p}: validation error: {e}")
            continue

    if errors and strict:
        raise SpecimenIssuesLoadError(errors)
    return IssuesLoadResult(items=items, errors=errors)


def _jsonnet_load_issues_dir(spec_dir: Path, strict: bool = True) -> IssuesLoadResult:
    return _jsonnet_load_dir(
        spec_dir,
        "issues",
        True,
        strict=strict,
        allow_missing=False,
    )


def _jsonnet_load_false_positives_dir(
    spec_dir: Path,
    strict: bool = True,
) -> IssuesLoadResult:
    """Load false positives from false_positives/ and force should_flag=False.

    If directory does not exist, returns empty set without error.
    """
    return _jsonnet_load_dir(
        spec_dir,
        "false_positives",
        False,
        strict=strict,
        allow_missing=True,
    )


def _xdg_cache_base() -> Path:
    # Prefer shared cache dir alongside existing helpers

    root = Path(user_cache_dir(appname="adgn-llm", appauthor=False)) / "specimens"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _extract_tar_gz_to_temp(archive: Path) -> Path:
    tmpdir = Path(tempfile.mkdtemp(prefix="adgn-specimen-extract-"))
    with tarfile.open(archive, "r:gz") as tf:
        tf.extractall(tmpdir)
    for p in tmpdir.iterdir():
        if p.is_dir():
            return p.resolve()
    return tmpdir


def _repack_dir_with_mtime(src_dir: Path, out_archive: Path, mtime: int = 0) -> None:
    out_archive.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_archive.with_suffix(".tmp")

    def _filter(ti: tarfile.TarInfo) -> tarfile.TarInfo | None:
        # Exclude VCS internals from archives to avoid permission issues and reduce size
        # Skip any member whose path includes a '.git' segment
        parts = ti.name.split("/")
        if ".git" in parts:
            return None
        ti.mtime = int(mtime)
        # Preserve uid/gid; determinism here only requires pinned mtime
        return ti

    with tarfile.open(tmp, "w:gz", format=tarfile.PAX_FORMAT) as tf:
        if os.environ.get("ADGN_DEBUG_SPECIMEN") == "1":
            logger.debug(
                "[specimen] repacking %s -> %s (filter .git, mtime=%s)",
                src_dir,
                out_archive,
                mtime,
            )
        tf.add(src_dir, arcname=Path(src_dir).name, filter=_filter)
    tmp.replace(out_archive)


def _repack_tar_with_mtime(archive: Path, mtime: int = 0) -> Path:
    extracted = _extract_tar_gz_to_temp(archive)
    _repack_dir_with_mtime(extracted, archive, mtime=mtime)
    shutil.rmtree(extracted, ignore_errors=True)
    return archive


def _default_gitconfig() -> Path | None:
    cfg = pkg_dir() / "gitconfig.local"
    return cfg if cfg.exists() else None


def _download_github_to(owner: str, repo: str, ref: str, dest: Path) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = urlunparse(("https", "codeload.github.com", f"/{owner}/{repo}/tar.gz/{ref}", "", "", ""))
    tmp = dest.with_suffix(".tmp")
    try:
        with urlopen(url) as resp:
            tmp.write_bytes(resp.read())
        tmp.replace(dest)
        return True
    except (URLError, HTTPError):
        if tmp.exists():
            tmp.unlink()
        return False


def _create_archive_from_git(
    url: str,
    ref: str,
    out_archive: Path,
    gitconfig: Path | None,
) -> bool:
    tmpdir = Path(tempfile.mkdtemp(prefix="adgn-specimen-git-"))

    try:
        # Check if URL points to a bundle file
        if url.startswith("file://"):
            file_path = url.removeprefix("file://")
            if file_path.endswith(".bundle"):
                # For bundles, use subprocess since pygit2 doesn't handle bundles well
                env = dict(**os.environ)
                if gitconfig is not None:
                    env["GIT_CONFIG_GLOBAL"] = str(gitconfig.expanduser().resolve())

                # Clone from bundle using subprocess
                subprocess.run(
                    ["git", "clone", file_path, str(tmpdir)],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=env,
                )
                subprocess.run(
                    ["git", "-C", str(tmpdir), "checkout", "--detach", ref],
                    check=True,
                    env=env,
                )
            else:
                # Regular file:// repository - use standard approach with subprocess
                # (pygit2 has issues with file:// URLs)
                env = dict(**os.environ)
                if gitconfig is not None:
                    env["GIT_CONFIG_GLOBAL"] = str(gitconfig.expanduser().resolve())

                subprocess.run(
                    ["git", "init", str(tmpdir)],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    env=env,
                )
                subprocess.run(
                    ["git", "-C", str(tmpdir), "remote", "add", "origin", url],
                    check=True,
                    env=env,
                )
                subprocess.run(
                    ["git", "-C", str(tmpdir), "fetch", "--depth", "1", "origin", ref],
                    check=True,
                    env=env,
                )
                subprocess.run(
                    ["git", "-C", str(tmpdir), "checkout", "--detach", ref],
                    check=True,
                    env=env,
                )
        else:
            # For non-file URLs, fall back to subprocess for now
            # (pygit2 network operations can be complex with auth)
            env = dict(**os.environ)
            if gitconfig is not None:
                env["GIT_CONFIG_GLOBAL"] = str(gitconfig.expanduser().resolve())

            subprocess.run(
                ["git", "init", str(tmpdir)],
                check=True,
                stdout=subprocess.DEVNULL,
                env=env,
            )
            subprocess.run(
                ["git", "-C", str(tmpdir), "remote", "add", "origin", url],
                check=True,
                env=env,
            )
            subprocess.run(
                ["git", "-C", str(tmpdir), "fetch", "--depth", "1", "origin", ref],
                check=True,
                env=env,
            )
            subprocess.run(
                ["git", "-C", str(tmpdir), "checkout", "--detach", ref],
                check=True,
                env=env,
            )

        # Drop VCS internals to keep archives small and writable on extract
        shutil.rmtree(tmpdir / ".git", ignore_errors=True)
        _repack_dir_with_mtime(tmpdir, out_archive, mtime=0)
        return True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def ensure_archive_for_specimen_slug(
    man: SpecimenDoc,
    manifest_path: Path,
    gitconfig: Path | None,
) -> Path:
    """Ensure a cached archive exists for the specimen.

    The slug is computed from the manifest path as repo/name.
    Cache is stored at ~/.cache/adgn-llm/specimens/{repo}/{name}.tar.gz
    """
    gitconfig = gitconfig or _default_gitconfig()
    # Extract hierarchical slug from path: specimens/{repo}/{name}/manifest.yaml -> repo/name
    specimen_dir = manifest_path.parent
    repo_name = specimen_dir.parent.name
    specimen_name = specimen_dir.name
    slug = f"{repo_name}/{specimen_name}"
    # Cache hierarchically: ~/.cache/adgn-llm/specimens/{repo}/{name}.tar.gz
    out = _xdg_cache_base() / repo_name / f"{specimen_name}.tar.gz"
    if os.environ.get("ADGN_DEBUG_SPECIMEN") == "1":
        logger.debug("[specimen] ensure_archive_for_specimen_slug slug=%s out=%s", slug, out)
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(man.source, GitHubSource):
        if _download_github_to(man.source.org, man.source.repo, man.source.ref, out):
            _repack_tar_with_mtime(out, mtime=0)
            return out
        if (
            _create_archive_from_git(
                urlunparse(
                    (
                        "https",
                        "github.com",
                        f"/{man.source.org}/{man.source.repo}.git",
                        "",
                        "",
                        "",
                    )
                ),
                man.source.ref,
                out,
                gitconfig,
            )
            and out.exists()
        ):
            return out
    elif isinstance(man.source, GitSource):
        if man.source.url.startswith("https://github.com/"):
            parts = (
                man.source.url.removeprefix("https://github.com/")
                .rstrip("/")
                .removesuffix(".git")
                .split("/")
            )
            if len(parts) >= 2 and _download_github_to(
                parts[0],
                parts[1],
                man.source.ref,
                out,
            ):
                _repack_tar_with_mtime(out, mtime=0)
                return out
        # Resolve relative file:// URLs relative to the manifest directory
        url = man.source.url
        if url.startswith("file://"):
            # Remove the file:// prefix
            file_path = url.removeprefix("file://")
            # If it's a relative path, resolve it relative to manifest directory
            if not file_path.startswith("/"):
                resolved_path = (manifest_path.parent / file_path).resolve()
                url = f"file://{resolved_path}"

        if (
            _create_archive_from_git(url, man.source.ref, out, gitconfig)
            and out.exists()
        ):
            return out
    elif isinstance(man.source, LocalSource):
        src = (manifest_path.parent / man.source.root).resolve()
        _repack_dir_with_mtime(src, out, mtime=0)
        return out
    raise SystemExit(
        f"Can't archive specimen cache for '{slug}' (source={type(man.source).__name__}); ",
    )


def resolve_source_root(
    man: SpecimenDoc,
    manifest_path: Path,
    gitconfig: Path | None,
) -> Path:
    gitconfig = gitconfig or _default_gitconfig()
    if isinstance(man.source, GitHubSource | GitSource):
        archive = ensure_archive_for_specimen_slug(man, manifest_path, gitconfig)
        return _extract_tar_gz_to_temp(archive)
    if isinstance(man.source, LocalSource):
        # Use existing local copy helper for consistency
        src = (manifest_path.parent / man.source.root).resolve()
        tmpdir = Path(tempfile.mkdtemp(prefix="adgn-specimen-local-"))
        dest = tmpdir / src.name
        shutil.copytree(src, dest)
        return dest
    raise SystemExit(f"Unsupported source type: {type(man.source)}")


def list_specimen_names(base: Path) -> list[str]:
    """List all specimen names in hierarchical format (repo/name).

    Specimens are organized as:
      specimens/
        {repo}/
          {name}/
            manifest.yaml

    Returns specimen IDs like "ducktape/2025-11-20-adgn", "crush/2025-08-30-internal_db"
    """
    names = []
    for repo_dir in base.iterdir():
        if not repo_dir.is_dir() or repo_dir.name.startswith(("_", ".")):
            continue
        for specimen_dir in repo_dir.iterdir():
            if specimen_dir.is_dir() and (specimen_dir / "manifest.yaml").exists():
                names.append(f"{repo_dir.name}/{specimen_dir.name}")
    return sorted(names)


def find_specimens_base() -> Path:
    """Resolve the installed specimens directory deterministically via package resources.

    This must exist inside the installed package; no filesystem fallbacks are used.
    """
    traversable = resources.files("adgn.props").joinpath("specimens")
    with resources.as_file(traversable) as p:
        if not p.exists() or not p.is_dir():
            raise FileNotFoundError(
                f"Specimens directory not found in package resources: {p}",
            )
        return p


def resolve_manifest_arg(arg: str | None, base: Path | None = None) -> Path | None:
    """Resolve a specimen identifier or path to its manifest.yaml.

    Args:
        arg: Specimen ID like "ducktape/2025-11-20-adgn" or filesystem path
        base: Specimens base directory (defaults to find_specimens_base())

    Returns:
        Path to manifest.yaml or None if not found
    """
    if arg is None:
        return None
    path = Path(arg)
    if path.exists():
        if path.is_dir():
            yaml_cand = path / "manifest.yaml"
            return yaml_cand if yaml_cand.exists() else None
        return path if path.suffix.lower() in {".yaml", ".yml"} else None
    base_dir = base or find_specimens_base()
    # Try direct hierarchical path (repo/name)
    yaml_cand = base_dir / arg.replace("/", os.sep) / "manifest.yaml"
    if yaml_cand.exists():
        return yaml_cand
    # Try prefix matching for convenience
    matches = [n for n in list_specimen_names(base_dir) if n.startswith(arg)]
    if len(matches) == 1:
        mdir = base_dir / matches[0].replace("/", os.sep)
        return (mdir / "manifest.yaml") if (mdir / "manifest.yaml").exists() else None
    return None


@dataclass(frozen=True)
class SpecimenRecord:
    slug: str
    manifest_path: Path
    manifest: SpecimenDoc
    issues: dict[str, IssueRecord]
    false_positives: dict[str, IssueRecord]

    @asynccontextmanager
    async def hydrated_copy(self, gitconfig: Path | None = None) -> AsyncIterator[Path]:
        """Yield a fresh private working tree path under $HOME for Docker-friendly mounts; clean up on exit.

        On macOS/Docker Desktop, mounts must be under $HOME to be shared with the VM. We therefore extract/copy under
        ~/.cache/adgn-llm/workspaces/<slug>_<ts>/ and yield the single extracted top-level directory.
        """
        gitconfig = gitconfig or _default_gitconfig()
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
                archive = ensure_archive_for_specimen_slug(
                    self.manifest,
                    self.manifest_path,
                    gitconfig,
                )
                with tarfile.open(archive, "r:gz") as tf:
                    members = [m for m in tf.getmembers() if ".git" not in m.name.split("/")]
                    if os.environ.get("ADGN_DEBUG_SPECIMEN") == "1":
                        total = len(tf.getmembers())
                        filtered = len(members)
                        logger.debug(
                            "[specimen] extracting %s members=%s/%s (filtered .git)",
                            archive,
                            filtered,
                            total,
                        )
                    tf.extractall(mount_root, members=members)
                    if os.environ.get("ADGN_DEBUG_SPECIMEN") == "1":
                        git_dirs = list((mount_root).rglob(".git"))
                        logger.debug("[specimen] post-extract .git dirs: %d", len(git_dirs))
                        for p in git_dirs[:10]:
                            logger.debug("    %s", p)
            elif isinstance(self.manifest.source, LocalSource):
                src = (self.manifest_path.parent / self.manifest.source.root).resolve()
                # For local specimens, materialize directly into mount_root (no extra subdir)
                shutil.copytree(src, mount_root, dirs_exist_ok=True)
            else:  # pragma: no cover - guarded by SpecimenDoc model
                raise SystemExit(
                    f"Unsupported source type: {type(self.manifest.source)}",
                )

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


class SpecimenRegistry:
    """Entry point for listing and obtaining specimen records (code-only facade).

    DI-friendly: pass in a preloaded mapping for tests; use load_* in app code.
    """

    def __init__(self, specimens: dict[str, SpecimenRecord]) -> None:
        # No I/O here; accept fully materialized data
        self._specimens = specimens

    @classmethod
    def load_strict(cls, slug: str, base: Path | None = None) -> SpecimenRecord:
        rec, errors = cls.load_lenient(slug, base=base)
        if errors:
            raise SpecimenIssuesLoadError(errors)
        return rec

    @classmethod
    def load_lenient(
        cls,
        slug: str,
        base: Path | None = None,
    ) -> tuple[SpecimenRecord, list[str]]:
        """Load a specimen by hierarchical ID (e.g., 'ducktape/2025-11-20-adgn')."""
        base_dir = base or find_specimens_base()
        manifest_path = (base_dir / slug.replace("/", os.sep) / "manifest.yaml").resolve()
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise SystemExit(f"Manifest must be a mapping: {manifest_path}")
        man = SpecimenDoc.model_validate(raw)
        res_pos = _jsonnet_load_issues_dir(manifest_path.parent, strict=False)
        res_fp = _jsonnet_load_false_positives_dir(manifest_path.parent, strict=False)
        rec = SpecimenRecord(
            slug=slug,
            manifest_path=manifest_path,
            manifest=man,
            issues={it.core.id: it for it in res_pos.items},
            false_positives={it.core.id: it for it in res_fp.items},
        )
        return rec, [*res_pos.errors, *res_fp.errors]

    @property
    def specimen_ids(self) -> list[str]:
        return sorted(self._specimens.keys())
