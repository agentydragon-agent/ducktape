from __future__ import annotations

import fnmatch
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from collections.abc import Iterable
from typing import Any, Annotated, Literal, cast
from pathlib import Path
from tempfile import NamedTemporaryFile
import warnings
import _jsonnet
import yaml

from adgn_llm.properties.prop_utils import (
    PropertyID,
    properties_root,
    validate_property_ids,
)
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from platformdirs import user_cache_dir
from pydantic import BaseModel, ConfigDict, model_validator, Field


# Specimen schema (v2): source/scope live alongside items in Jsonnet docs
class GitSource(BaseModel):
    vcs: Literal["git"]
    url: str
    ref: str


class GitHubSource(BaseModel):
    vcs: Literal["github"]
    org: str
    repo: str
    ref: str


class LocalSource(BaseModel):
    vcs: Literal["local"]
    root: str = "."


Source = Annotated[GitSource | GitHubSource | LocalSource, Field(discriminator="vcs")]


class Scope(BaseModel):
    include: list[str]
    exclude: list[str] | None = None


class SpecimenDoc(BaseModel):
    """Unified specimen document (v2): source/scope and items (Jsonnet-only)."""

    source: Source
    scope: Scope
    items: list["Issue"]


def _warn_deprecated_model(message: str) -> None:
    """Emit a standardized deprecation warning for legacy protocol models."""
    warnings.warn(message, DeprecationWarning, stacklevel=2)


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
    """A single occurrence/location of an Issue.

    - `files` maps file paths -> either a list of LineRange objects (one or more
      ranges within that file) or `None` to indicate an unspecified anchor in the
      file. A single Occurrence may reference multiple files (e.g., a multi-file
      code fragment) but represents a single logical location instance.
    - `note` is an optional, occurrence-level explanatory string. Use it for
      brief, local context (what to change or why this instance matters). Do not
      duplicate the Issue.rationale here.

    Authoring guidance (single source of truth):
    - An Issue represents one logical problem (id, rationale, properties). Use
      one Issue with multiple Occurrences when the same logical problem appears
      in several places but should be tracked together.
    - Prefer Occurrence-level notes for location-specific guidance; keep the
      Issue.rationale for the global explanation and acceptance criteria.
    """

    files: dict[str, list[LineRange] | None]
    note: str | None = Field(
        default=None,
        description=(
            "Occurrence-specific note. Use for details unique to this occurrence; "
            "do not repeat the issue-level rationale here."
        ),
    )


# Annotation models for machine-readable linter outputs
class PropertyIncorrectlyAssigned(BaseModel):
    kind: Literal["PROPERTY_INCORRECTLY_ASSIGNED"] = Field(
        description="Discriminator for property incorrectly assigned"
    )
    property: PropertyID
    rationale: str

    model_config = ConfigDict(extra="forbid")


class PropertyShouldBeAssigned(BaseModel):
    kind: Literal["PROPERTY_SHOULD_BE_ASSIGNED"] = Field(
        description="Discriminator for property that should be assigned"
    )
    property: PropertyID
    rationale: str

    model_config = ConfigDict(extra="forbid")


class AnchorIncorrect(BaseModel):
    kind: Literal["ANCHOR_INCORRECT"] = Field(description="Discriminator for incorrect anchor")
    correction: "Correction"
    rationale: str

    model_config = ConfigDict(extra="forbid")


class FalsePositive(BaseModel):
    kind: Literal["FALSE_POSITIVE"] = Field(description="Discriminator for false-positive marking")
    rationale: str

    model_config = ConfigDict(extra="forbid")


class OtherError(BaseModel):
    kind: Literal["OTHER_ERROR"] = Field(description="Discriminator for other errors / fallback")
    description: str

    model_config = ConfigDict(extra="forbid")


# Rationale-focused annotations
class RationaleError(BaseModel):
    kind: Literal["RATIONALE_ERROR"] = Field(description="Discriminator for rationale being factually incorrect")
    error_description: str

    model_config = ConfigDict(extra="forbid")


class RationaleImprovement(BaseModel):
    kind: Literal["RATIONALE_IMPROVEMENT"] = Field(
        description="Discriminator for non-blocking rationale improvement suggestion"
    )
    suggested_improvement: str

    model_config = ConfigDict(extra="forbid")


# Small correction type re-using existing LineRange
class Correction(BaseModel):
    file: str
    range: LineRange

    model_config = ConfigDict(extra="forbid")


IssueLintFinding = Annotated[
    PropertyIncorrectlyAssigned
    | PropertyShouldBeAssigned
    | AnchorIncorrect
    | FalsePositive
    | OtherError
    | RationaleError
    | RationaleImprovement,
    Field(discriminator="kind"),
]


class IssueLintFindingRecord(BaseModel):
    """A single lint finding with optional human rationale/explanation.

    - `finding` is the typed, discriminated union describing the kind of problem
      and structured payload.
    - `rationale` is the human-readable explanation for *this finding* — why
      the linter produced it or what to do about it.
    """

    finding: IssueLintFinding
    rationale: str | None = None

    model_config = ConfigDict(extra="forbid")


class SpecimenIssuesLoadError(Exception):
    """Raised when per-issue Jsonnet evaluation/validation yields any errors in strict mode.

    Carries a list of human-readable error lines. __str__ joins them with newlines
    so pytest and CLIs surface a readable summary.
    """

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__(str(self))

    def __str__(self) -> str:  # pragma: no cover - exercised via message rendering
        return "Specimen issue loading errors:\n" + "\n".join(self.errors)


class Issue(BaseModel):
    """Issue (legacy) — metadata coupled with its occurrences.

    NOTE: This model is deprecated in favor of IssueCore (metadata) + separate
    Occurrence objects, but remains supported for backward compatibility.

    Semantics (single-source of truth):
    - An Issue represents one logical problem (the "what" and "why").
    - It can have multiple occurrences (instances) where that problem appears.
      Each Occurrence describes the specific file(s)/line ranges and optional
      occurrence-level note describing local context or suggested edits.

    When to use which shape:
    - Use I.issueOneOccurrence when the issue is a single logical change that
      must be applied atomically across multiple files (delete wrapper + update
      caller together).
    - Use I.issueOccurrencesFromLines to record multiple independent
      manifestations of the same issue that can be fixed separately.

    Examples (punchy):

    1) "1 issue, 2 occurrences" — independent fixes (Pydantic/JSON form)
       JSON example:
       {
         "id": "iss-trailing-whitespace",
         "should_flag": true,
         "rationale": "Trailing whitespace in tests",
         "properties": ["no-dead-code"],
         "instances": [
           { "files": { "tests/a.py": [ { "start_line": 10 } ] } },
           { "files": { "tests/b.py": [ { "start_line": 20 } ] } }
         ]
       }

    2) "1 occurrence, 2 locations" — one atomic fix across files (Pydantic/JSON form)
       JSON example:
       {
         "id": "iss-remove-wrapper",
         "should_flag": true,
         "rationale": "Remove deprecated wrapper and update its sole caller",
         "properties": ["no-oneoff-vars-and-trivial-wrappers"],
         "instances": [
           {
             "files": {
               "pkg/wrapper.py": [ { "start_line": 12, "end_line": 20 } ],
               "pkg/caller.py":  [ { "start_line": 45, "end_line": 52 } ]
             }
           }
         ]
       }

    Keep the Issue.rationale as the authoritative explanation; occurrence
    notes should be short and local.
    """

    id: str
    should_flag: bool
    rationale: str
    properties: list[PropertyID] = []
    gap_note: str | None = None

    model_config = ConfigDict(extra="forbid")
    instances: list[Occurrence]

    def model_post_init(self, _: Any) -> None:  # type: ignore[override]
        _warn_deprecated_model(
            "Issue is deprecated: use IssueCore + Occurrence(s). This model will be removed after migration."
        )

    @model_validator(mode="after")
    def _validate_self(self) -> "Issue":
        validate_property_ids(self.properties)
        if not self.instances:
            raise ValueError("`instances` must contain at least one occurrence")
        return self

    @property
    def files_touched(self) -> set[str]:
        paths: set[str] = set()
        for occ in self.instances or []:
            paths.update(occ.files.keys())
        return paths


class IssueCore(BaseModel):
    """Issue metadata without occurrences.

    The canonical, minimal header describing a logical problem. When sending or
    storing per-location data separately, pair an IssueCore with one or more
    Occurrence objects rather than repeating metadata.

    - Use IssueCore for APIs or tooling that pass around a single occurrence
      together with metadata (e.g., lint-issue flows).
    - Prefer not to duplicate IssueCore fields across multiple files; instead
      reference a single Issue (id) and attach Occurrence(s) describing locations.
    """

    id: str
    should_flag: bool
    rationale: str
    properties: list[PropertyID] = []
    gap_note: str | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _validate_self(self) -> "IssueCore":
        validate_property_ids(self.properties)
        return self

    @classmethod
    def from_issue(cls, issue: "Issue") -> "IssueCore":
        return cls(
            id=issue.id,
            should_flag=issue.should_flag,
            rationale=issue.rationale,
            properties=list(issue.properties),
            gap_note=issue.gap_note,
        )


class SpecimenIssues(BaseModel):
    """DEPRECATED: Will be superseded by SpecimenGroundTruth (positives/negatives).

    Kept for compatibility with existing Jsonnet pipelines until migration completes.
    """

    items: list[Issue]

    def model_post_init(self, _: Any) -> None:  # type: ignore[override]
        _warn_deprecated_model("SpecimenIssues is deprecated: use SpecimenGroundTruth protocol.")

    def filter_by_paths(
        self,
        include: list[str] | None,
        exclude: list[str] | None = None,
    ) -> SpecimenIssues:
        if not include and not exclude:
            return self

        def matches_any(path: str, globs: list[str] | None) -> bool:
            if not globs:
                return False
            return any(fnmatch.fnmatch(path, g) for g in globs)

        filtered: list[Issue] = []
        for issue in self.items:
            file_paths = list(issue.files_touched)
            keep = any(matches_any(p, include) for p in file_paths) if include else True
            if exclude and any(matches_any(p, exclude) for p in file_paths):
                keep = False
            if keep:
                filtered.append(issue)
        return SpecimenIssues.model_validate({"items": filtered})


def find_specimens_base() -> Path:
    # 1) importlib.resources
    p = properties_root() / "specimens"
    if p.exists() and p.is_dir():
        return p
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
    return sorted(p.name for p in base.iterdir() if p.is_dir() and (p / "manifest.yaml").exists())


def resolve_manifest_arg(arg: str | None, base: Path | None = None) -> Path | None:
    if arg is None:
        return None
    path = Path(arg)
    # Accept only YAML manifests (file path or directory containing manifest.yaml)
    if path.exists():
        if path.is_dir():
            yaml_cand = path / "manifest.yaml"
            return yaml_cand if yaml_cand.exists() else None
        return path if path.suffix.lower() in {".yaml", ".yml"} else None
    base_dir = base or find_specimens_base()
    yaml_cand = base_dir / arg / "manifest.yaml"
    if yaml_cand.exists():
        return yaml_cand
    # unique prefix resolution restricted to YAML-backed specimens
    matches = [n for n in list_specimen_names(base_dir) if n.startswith(arg)]
    if len(matches) == 1:
        mdir = base_dir / matches[0]
        return (mdir / "manifest.yaml") if (mdir / "manifest.yaml").exists() else None
    return None


def load_manifest(path: Path) -> SpecimenDoc:
    """Read specimen manifest (YAML only) and normalize to SpecimenDoc shape.

    Normalizations:
    - Map source.type -> source.vcs (YAML uses 'type'; Pydantic model discriminates on 'vcs').
    - Ensure items: [] exists (issues are loaded separately from issues/*.libsonnet).
    """
    if path.suffix.lower() not in {".yaml", ".yml"}:
        raise SystemExit(f"Unsupported manifest format (YAML required): {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise SystemExit(f"Manifest must be a mapping: {path}")
    data = dict(raw)
    # Normalize source discriminator key
    src = data.get("source")
    if isinstance(src, dict) and "vcs" not in src and "type" in src:
        # Copy to avoid mutating the original mapping unexpectedly
        src = dict(src)
        src["vcs"] = src.pop("type")
        data["source"] = src
    # Ensure items list is present (empty by default; issues loaded separately)
    data.setdefault("items", [])
    return SpecimenDoc.model_validate(data)


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


def _repack_dir_with_mtime(src_dir: Path, out_archive: Path, mtime: int = 0) -> None:
    """
    Create a gzip tarball of src_dir with all TarInfo.mtime set to mtime and
    normalized ownership fields for deterministic archives.
    """
    out_archive.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_archive.with_suffix(".tmp")

    def _filter(ti: tarfile.TarInfo) -> tarfile.TarInfo:
        ti.mtime = int(mtime)
        # Normalize ownership and names to reduce nondeterminism
        ti.uid = 0
        ti.gid = 0
        ti.uname = ""
        ti.gname = ""
        return ti

    with tarfile.open(tmp, "w:gz", format=tarfile.PAX_FORMAT) as tf:
        tf.add(src_dir, arcname=Path(src_dir).name, filter=_filter)
    tmp.replace(out_archive)


def _repack_tar_with_mtime(archive: Path, mtime: int = 0) -> Path:
    """
    Repack an existing tar.gz archive to normalize mtimes and ownership.
    This extracts the archive to a temp dir and re-creates it with normalized
    TarInfo fields. Returns the (replaced) archive path.
    """
    extracted = _extract_tar_gz_to_temp(archive)
    _repack_dir_with_mtime(extracted, archive, mtime=mtime)
    shutil.rmtree(extracted, ignore_errors=True)
    return archive


def ensure_archive_for_specimen_slug(
    man: SpecimenDoc,
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
            # Normalize mtimes/ownership in the downloaded archive for determinism
            _repack_tar_with_mtime(out, mtime=0)
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
                # Normalize downloaded archive
                _repack_tar_with_mtime(out, mtime=0)
                return out if out.exists() else out
        if _create_archive_from_git(man.source.url, man.source.ref, out, gitconfig) and out.exists():
            return out
    elif isinstance(man.source, LocalSource):
        # Tar local directory under manifest. Repack with normalized mtimes so
        # cached archives are deterministic across runs.
        src = (manifest_path.parent / man.source.root).resolve()
        _repack_dir_with_mtime(src, out, mtime=0)
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
    try:
        # Repack the checked-out git tree into a deterministic tarball
        _repack_dir_with_mtime(Path(tmp_checkout), out_archive, mtime=0)
        return True
    finally:
        shutil.rmtree(tmp_checkout, ignore_errors=True)


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
    man: SpecimenDoc,
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
        manifest: SpecimenDoc,
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

    def load_issues(self, strict: bool = False) -> SpecimenIssues:
        """Load specimen issues.

        Behavior:
        - If a directory `issues/` exists under the specimen, evaluate each
          `issues/*.libsonnet` as a standalone Jsonnet expression, normalize the
          produced object, and validate against the canonical `Issue` model.
        - If `issues/` is absent, fall back to the legacy `issues.libsonnet` file.

        This loader performs in-memory assembly only and does not write any
        assembled artifacts to disk.
        """
        spec_dir = self.manifest_path.parent
        issues_dir = spec_dir / "issues"

        if not issues_dir.is_dir():
            raise SpecimenIssuesLoadError([f"No issues/ directory found under: {spec_dir}"])
        items: list[Any] = []
        errors: list[str] = []
        for p in sorted(issues_dir.glob("*.libsonnet")):
            stem = p.stem
            # Ensure Jsonnet can find the shared helper file (specimen_issues.libsonnet)
            jsonnet_libdir = Path(__file__).resolve().parent

            # Custom importer: resolve relative to importing file first, then against our fixed library dir
            def _importer(base: str, rel: str) -> tuple[str, bytes]:
                # 1) relative to the importing file
                cand1 = (Path(base) / rel).resolve()
                if cand1.is_file():
                    return str(cand1), cand1.read_bytes()
                # 2) fall back to package library root (handles '../../specimen_issues.libsonnet' style paths)
                #    If rel has directories like ../, honor only the basename when searching libdir.
                rel_name = Path(rel).name
                cand2 = (jsonnet_libdir / rel_name).resolve()
                if cand2.is_file():
                    return str(cand2), cand2.read_bytes()
                raise RuntimeError(f"import not found: base={base!r} rel={rel!r}")

            try:
                raw = cast(Any, _jsonnet).evaluate_file(
                    str(p),
                    jpathdir=[str(jsonnet_libdir)],
                    import_callback=_importer,
                )
            except Exception as e:
                errors.append(f"{p}: Jsonnet evaluation error: {e}")
                continue
            # Strict, single-path parse: expect Jsonnet to emit a JSON text string
            if not isinstance(raw, str):
                errors.append(f"{p}: Jsonnet evaluator returned non-string (expected JSON text)")
                continue
            try:
                obj = json.loads(raw)
            except Exception as e:
                errors.append(f"{p}: Failed to parse Jsonnet output as JSON: {e}")
                continue

            if not isinstance(obj, dict):
                errors.append(f"{p}: Jsonnet did not produce an object (got {type(obj)})")
                continue

            # Enforce filename-derived id if not present; reject mismatch
            if "id" in obj and obj["id"] != stem:
                errors.append(f"{p}: embedded id '{obj.get('id')}' does not match filename '{stem}'")
                continue
            if "id" not in obj:
                obj["id"] = stem

            # Try to validate into the canonical Issue model (legacy model kept here)
            try:
                # Note: we validate with the existing Issue model for backward compat
                validated = Issue.model_validate(obj)
                items.append(validated)
            except Exception as e:
                errors.append(f"{p}: validation error: {e}")
                continue

        # If any errors were collected, either raise (strict) or proceed with valid items only (loose)
        if errors and strict:
            raise SpecimenIssuesLoadError(errors)

        # Build SpecimenIssues from validated items (legacy shape expects Issue instances)
        return SpecimenIssues.model_validate({"items": items})

    def get_issue(self, issue_id: str):
        issues = self.load_issues()
        match = next((it for it in issues.items if it.id == issue_id), None)
        if match is None:
            raise SystemExit(f"Issue id not found in specimen issues: {issue_id}")
        return match
