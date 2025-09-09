from __future__ import annotations

import fnmatch
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from collections.abc import Iterable
from functools import lru_cache
from typing import Any
from pathlib import Path
from tempfile import NamedTemporaryFile
import _jsonnet

# ---- Canonical specimen issues schema (Jsonnet-only) ----
from adgn_llm.properties.prop_utils import PropertyID, properties_root, validate_property_ids
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

import yaml
from platformdirs import user_cache_dir
from pydantic import BaseModel, ConfigDict, model_validator, Field

from .specimen_frontmatter import GitHubSource, GitSource, LocalSource, SpecimenManifest


# properties_root moved to prop_utils; import from there to avoid duplication
# def properties_root() -> Path: ... (see adgn_llm.properties.prop_utils)


# find_property_files moved to prop_utils; import from there to avoid duplication
# def find_property_files(...): ... (see adgn_llm.properties.prop_utils)


@lru_cache(maxsize=1)
def _list_known_property_ids() -> set[PropertyID]:
    defs_root = properties_root() / "definitions"
    ids: set[PropertyID] = set()
    if defs_root.exists():
        for md in defs_root.rglob("*.md"):
            ids.add(PropertyID(md.stem))
    return ids


def _validate_property_ids(props: list[PropertyID]) -> None:
    # Back-compat wrapper; delegate to shared prop_utils
    return validate_property_ids(props)


class LineRange(BaseModel):
    start_line: int = Field(..., description="1-based start line number")
    end_line: int | None = Field(
        default=None,
        description="1-based end line number (inclusive); omit for single-line anchor",
    )

    @model_validator(mode="after")
    def _validate_range(self) -> "LineRange":
        if self.start_line < 1:
            raise ValueError("start_line must be >= 1")
        if self.end_line is not None and self.end_line < self.start_line:
            raise ValueError("end_line must be >= start_line when provided")
        return self


class Occurrence(BaseModel):
    files: dict[str, list[LineRange] | None]


class Issue(BaseModel):
    id: str
    should_flag: bool
    rationale: str
    properties: list[PropertyID] = []
    gap_note: str | None = None

    model_config = ConfigDict(extra="ignore")
    instances: list[Occurrence]

    @model_validator(mode="after")
    def _validate_self(self) -> Issue:
        _validate_property_ids(self.properties)
        if not self.instances:
            raise ValueError("`instances` must contain at least one occurrence")
        return self

    @property
    def files_touched(self) -> set[str]:
        paths: set[str] = set()
        for occ in self.instances or []:
            paths.update(occ.files.keys())
        return paths


class SpecimenIssues(BaseModel):
    items: list[Issue]

    def filter_by_paths(
        self,
        include: list[str],
        exclude: list[str] | None = None,
    ) -> SpecimenIssues:
        if not include and not exclude:
            return self

        def matches_any(path: str, globs: list[str] | None) -> bool:
            return bool(globs) and any(fnmatch.fnmatch(path, g) for g in globs)

        filtered: list[Issue] = []
        for issue in self.items:
            file_paths = list(issue.files_touched)
            keep = any(matches_any(p, include) for p in file_paths) if include else True
            if keep and exclude and any(matches_any(p, exclude) for p in file_paths):
                keep = False
            if keep:
                filtered.append(issue)
        return SpecimenIssues(items=filtered)


def load_specimen_issues(path: str | Path) -> SpecimenIssues:
    """Load SpecimenIssues from Jsonnet (.libsonnet/.jsonnet) only."""
    p = Path(path)
    suf = p.suffix.lower()
    if suf not in {".jsonnet", ".libsonnet"}:
        raise SystemExit(f"Canonical issues must be Jsonnet: {p}")
    json_str = _jsonnet.evaluate_file(str(p))
    data = json.loads(json_str)
    return SpecimenIssues.model_validate(data)


def find_specimens_base() -> Path:
    # 1) importlib.resources
    try:
        p = properties_root() / "specimens"
        if p.exists() and p.is_dir():
            return p
    except Exception:
        pass
    # 2) walk parents from this file for src tree
    here = Path(__file__).resolve()
    for parent in here.parents:
        for rel in (
            Path("src/adgn_llm/properties/specimens"),
            Path("adgn_llm/properties/specimens"),
        ):
            cand = (parent / rel).resolve()
            if cand.exists():
                return cand
    # Fallback
    return properties_root() / "specimens"


def list_specimen_names(base: Path) -> list[str]:
    return sorted(
        [p.name for p in base.iterdir() if p.is_dir() and (p / "manifest.yaml").exists()],
    )


def resolve_manifest_arg(arg: str | None, base: Path | None = None) -> Path | None:
    if arg is None:
        return None
    path = Path(arg)
    if path.exists():
        return path / "manifest.yaml" if path.is_dir() else path
    base_dir = base or find_specimens_base()
    cand = base_dir / arg / "manifest.yaml"
    if cand.exists():
        return cand
    # unique prefix
    matches = [n for n in list_specimen_names(base_dir) if n.startswith(arg)]
    if len(matches) == 1:
        return base_dir / matches[0] / "manifest.yaml"
    return None


def load_manifest(path: Path) -> SpecimenManifest:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return SpecimenManifest.model_validate(data)


def _xdg_cache_base() -> Path:
    base = Path(user_cache_dir(appname="adgn-llm", appauthor=False))
    root = base / "specimens"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _download_github_to(owner: str, repo: str, ref: str, dest: Path) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://codeload.github.com/{owner}/{repo}/tar.gz/{ref}"
    tmp = dest.with_suffix(".tmp")
    try:
        with urlopen(url) as resp:
            with NamedTemporaryFile(delete=False, dir=str(dest.parent)) as nf:
                nf.write(resp.read())
                tmp = Path(nf.name)
        os.replace(tmp, dest)
        return True
    except (URLError, HTTPError):
        # Network/HTTP error: no cache produced
        if tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass
        return False


def _extract_tar_gz_to_temp(archive: Path) -> Path:
    tmpdir = Path(tempfile.mkdtemp(prefix="adgn-specimen-extract-"))
    with tarfile.open(archive, "r:gz") as tf:
        tf.extractall(tmpdir)
    for p in tmpdir.iterdir():
        if p.is_dir():
            return p.resolve()
    return tmpdir


def ensure_archive_for_specimen_slug(
    man: SpecimenManifest,
    manifest_path: Path,
    gitconfig: Path | None,
) -> Path:
    """Ensure a cached tar.gz exists keyed by specimen slug (dir name of manifest).

    This wraps both GitHubSource and generic Git, producing one canonical cache:
      $XDG_CACHE_HOME/adgn-llm/specimens/by-slug/<slug>.tar.gz
    """
    slug = manifest_path.parent.name
    out = _xdg_cache_base() / "by-slug" / f"{slug}.tar.gz"
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    # Try fast GitHub codeload direct-to-dest when available
    if isinstance(man.source, GitHubSource):
        if _download_github_to(man.source.org, man.source.repo, man.source.ref, out):
            return out if out.exists() else out
        # Fallback: shallow checkout → tar.gz
        if (
            _create_archive_from_git(
                f"https://github.com/{man.source.org}/{man.source.repo}.git",
                man.source.ref,
                out,
                gitconfig,
            )
            and out.exists()
        ):
            return out
    elif isinstance(man.source, GitSource):
        if man.source.url.startswith("https://github.com/"):
            parts = man.source.url.removeprefix("https://github.com/").rstrip("/")
            parts = parts.removesuffix(".git")
            bits = parts.split("/")
            if len(bits) >= 2 and _download_github_to(bits[0], bits[1], man.source.ref, out):
                return out if out.exists() else out
        if _create_archive_from_git(man.source.url, man.source.ref, out, gitconfig) and out.exists():
            return out
    elif isinstance(man.source, LocalSource):
        # Tar local directory under manifest
        src = (manifest_path.parent / man.source.root).resolve()
        tmp = out.with_suffix(".tmp")
        with tarfile.open(tmp, "w:gz") as tf:
            tf.add(src, arcname=src.name)
        tmp.replace(out)
        return out
    # If we get here and out still missing, raise for caller to decide next step
    raise SystemExit(
        (
            f"Specimen cache not available for slug '{slug}' (source={type(man.source).__name__}); "
            f"unable to create archive"
        ),
    )


def _create_archive_from_git(
    url: str,
    ref: str,
    out_archive: Path,
    gitconfig: Path | None,
) -> bool:
    tmp_checkout = fresh_git_checkout_url(url, ref, gitconfig)
    out_archive.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_archive.with_suffix(".tmp")
    try:
        with tarfile.open(tmp, "w:gz") as tf:
            # Archive the directory tree at top-level folder
            tf.add(tmp_checkout, arcname=Path(tmp_checkout).name)
        tmp.replace(out_archive)
        return True
    finally:
        try:
            shutil.rmtree(tmp_checkout, ignore_errors=True)
        except Exception:
            pass


def fresh_git_checkout_url(url: str, ref: str, gitconfig: Path | None) -> Path:
    tmpdir = Path(tempfile.mkdtemp(prefix="adgn-specimen-git-"))
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
    return tmpdir


def fresh_local_copy(root: Path) -> Path:
    src = root.resolve()
    if not src.exists():
        raise SystemExit(f"Local source root not found: {src}")
    tmpdir = Path(tempfile.mkdtemp(prefix="adgn-specimen-local-"))
    dest = tmpdir / src.name
    shutil.copytree(src, dest)
    return dest


def build_scope_text(
    include: Iterable[str],
    exclude: Iterable[str] | None = None,
) -> str:
    inc = ", ".join(include)
    if exclude:
        return f"all files under {inc} (excluding: {', '.join(exclude)})"
    return f"all files under {inc}"


def resolve_source_root(
    man: SpecimenManifest,
    manifest_path: Path,
    gitconfig: Path | None,
) -> Path:
    """Resolve a fresh, private source root for a specimen manifest.

    Prefers a cached compressed archive under XDG cache; falls back to fresh git checkout when needed.
    """
    # Git sources (GitHub or generic): ensure a by-slug cached archive and extract
    if isinstance(man.source, (GitHubSource, GitSource)):
        archive = ensure_archive_for_specimen_slug(man, manifest_path, gitconfig)
        return _extract_tar_gz_to_temp(archive)

    # Local source: plain copy (no cache)
    if isinstance(man.source, LocalSource):
        return fresh_local_copy(manifest_path.parent / man.source.root)

    raise SystemExit(f"Unsupported source type: {type(man.source)}")


def load_single_issue(specimen: str, issue_id: str, gitconfig: str | None) -> tuple["Specimen", Path, Any]:
    """Resolve specimen, obtain code, and return (Specimen, root, Issue)."""
    sp = Specimen.load(specimen)
    # Optional default gitconfig fallback for private repos
    if gitconfig is None:
        cfg = properties_root() / "gitconfig.local"
        if cfg.exists():
            gitconfig = str(cfg)
    gc_path = Path(gitconfig).expanduser().resolve() if gitconfig else None
    root = sp.obtain_code(gitconfig=gc_path)
    issue = sp.get_issue(issue_id)
    if not issue.should_flag:
        raise SystemExit(f"Issue should_flag=false is not supported by linter: {issue_id}")
    return sp, root, issue


class Specimen:
    """Convenience wrapper around a specimen manifest + optional materialized source.

    - manifest_path: path to manifest.yaml
    - manifest: parsed SpecimenManifest (pydantic)
    - root: Path to working tree for analysis (defaults to manifest dir; set by materialize_source)
    """

    def __init__(
        self,
        manifest_path: Path,
        manifest: SpecimenManifest,
        root: Path,
    ) -> None:
        self.manifest_path = manifest_path
        self.manifest = manifest
        self.root = root

    @classmethod
    def load(cls, specimen_arg: str) -> Specimen:
        manifest_path = resolve_manifest_arg(specimen_arg)
        if manifest_path is None:
            raise SystemExit(f"Specimen not found: {specimen_arg}")
        man = load_manifest(manifest_path)
        # Default root is the manifest directory; call obtain_code() to obtain a fresh checkout/copy
        return cls(manifest_path, man, manifest_path.parent)

    def obtain_code(self, gitconfig: Path | None = None) -> Path:
        """Obtain a fresh, private checkout/copy of the specimen source and set self.root to it."""
        self.root = resolve_source_root(self.manifest, self.manifest_path, gitconfig)
        return self.root

    def load_issues(self) -> SpecimenIssues:
        spec_dir = self.manifest_path.parent
        path = spec_dir / "issues.libsonnet"
        if path.exists():
            return load_specimen_issues(path)
        raise SystemExit(f"No issues.libsonnet found under: {spec_dir}")

    def get_issue(self, issue_id: str):
        issues = self.load_issues()
        match = next((it for it in issues.items if it.id == issue_id), None)
        if match is None:
            raise SystemExit(f"Issue id not found in specimen issues: {issue_id}")
        return match
