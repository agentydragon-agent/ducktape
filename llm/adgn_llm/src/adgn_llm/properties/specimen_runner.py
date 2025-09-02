from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple
from urllib.request import urlopen
from urllib.error import URLError, HTTPError

import yaml
from importlib.resources import files

# Reuse the validated schema
from .specimen_frontmatter import SpecimenManifest, GitSource, GitHubSource, LocalSource


@dataclass
class RunnerConfig:
    dry_run: bool = False
    output_json: bool = False
    embed_paths: List[str] | None = None
    gitconfig: Optional[str] = None


def load_manifest(path: Path) -> SpecimenManifest:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return SpecimenManifest.model_validate(data)


def fresh_git_checkout_url(url: str, ref: str, gitconfig: Optional[str]) -> Path:
    """Create a fresh, shallow checkout of the given URL at ref in a private temp dir."""
    tmpdir = Path(tempfile.mkdtemp(prefix="adgn-specimen-git-"))
    env = dict(**os.environ)
    if gitconfig:
        env["GIT_CONFIG_GLOBAL"] = str(Path(gitconfig).expanduser().resolve())
    subprocess.run(["git", "init", str(tmpdir)], check=True, stdout=subprocess.DEVNULL, env=env)
    subprocess.run(["git", "-C", str(tmpdir), "remote", "add", "origin", url], check=True, env=env)
    subprocess.run(["git", "-C", str(tmpdir), "fetch", "--depth", "1", "origin", ref], check=True, env=env)
    subprocess.run(["git", "-C", str(tmpdir), "checkout", "--detach", ref], check=True, env=env)
    return tmpdir


def fresh_local_copy(root: Path) -> Path:
    """Copy a local directory to a private temp dir.

    Returns the absolute path to the copied root.
    """
    src = root.resolve()
    if not src.exists():
        raise FileNotFoundError(f"Local source root not found: {src}")
    tmpdir = Path(tempfile.mkdtemp(prefix="adgn-specimen-local-"))
    dest = tmpdir / src.name
    shutil.copytree(src, dest)
    return dest


def build_scope_text(include: Iterable[str], exclude: Optional[Iterable[str]] = None) -> str:
    inc = ", ".join(include)
    if exclude:
        exc = ", ".join(exclude)
        return f"all files under {inc} (excluding: {exc})"
    return f"all files under {inc}"


def find_specimens_base() -> Path:
    """Resolve specimens base directory (no env, no CLI override).

    Priority:
    1) importlib.resources package path: adgn_llm/properties/specimens
    2) Module-near source tree: walk parents to find src/adgn_llm/properties/specimens or adgn_llm/properties/specimens
    3) Git workspace root + known relative paths (llm/adgn_llm/src/...)
    """
    # 1) importlib.resources
    try:
        res = files("adgn_llm").joinpath("properties", "specimens")
        # Traversable may be a path or zip; prefer concrete path when available
        p = Path(res) if hasattr(res, "__fspath__") or isinstance(res, Path) else Path(str(res))
        if p.exists() and p.is_dir():
            return p
    except Exception:
        pass

    # 2) Walk parents from module file
    here = Path(__file__).resolve()
    for parent in here.parents:
        for rel in (
            Path("src/adgn_llm/properties/specimens"),
            Path("adgn_llm/properties/specimens"),
        ):
            cand = (parent / rel).resolve()
            if cand.exists():
                return cand

    # 3) Git workspace root heuristics
    try:
        proc = subprocess.run(["git", "rev-parse", "--show-toplevel"], check=True, capture_output=True, text=True)
        root = Path(proc.stdout.strip())
        for rel in (
            Path("llm/adgn_llm/src/adgn_llm/properties/specimens"),
            Path("src/adgn_llm/properties/specimens"),
            Path("adgn_llm/properties/specimens"),
        ):
            cand = (root / rel).resolve()
            if cand.exists():
                return cand
    except Exception:
        pass

    # Fallback: package-relative path (may not exist if data not included)
    return (here.parent / "specimens").resolve()


def list_specimen_names(base: Path) -> list[str]:
    names: list[str] = []
    if base.exists():
        for p in sorted(base.iterdir()):
            if p.is_dir() and (p / "manifest.yaml").exists():
                names.append(p.name)
    return names


def resolve_manifest_arg(arg: Optional[str], base: Path) -> Path | None:
    if arg is None:
        return None
    # If arg points to a file/dir on disk, respect it
    path = Path(arg)
    if path.exists():
        return path / "manifest.yaml" if path.is_dir() else path
    # Else, treat as specimen name under specimens/
    candidate = base / arg / "manifest.yaml"
    if candidate.exists():
        return candidate
    # Unique prefix support
    matches = [n for n in list_specimen_names(base) if n.startswith(arg)]
    if len(matches) == 1:
        return base / matches[0] / "manifest.yaml"
    return None


def parse_github_owner_repo(url: str) -> Optional[Tuple[str, str]]:
    # Supports https://github.com/owner/repo(.git) and git@github.com:owner/repo(.git)
    u = url.strip()
    if "github.com" not in u:
        return None
    if u.startswith("https://github.com/"):
        parts = u.removeprefix("https://github.com/").rstrip("/")
        if parts.endswith(".git"):
            parts = parts[:-4]
        bits = parts.split("/")
        if len(bits) >= 2:
            return bits[0], bits[1]
    if u.startswith("git@github.com:"):
        parts = u.removeprefix("git@github.com:").rstrip("/")
        if parts.endswith(".git"):
            parts = parts[:-4]
        bits = parts.split("/")
        if len(bits) >= 2:
            return bits[0], bits[1]
    return None


def try_download_github_archive(owner: str, repo: str, ref: str) -> Optional[Path]:
    url = f"https://codeload.github.com/{owner}/{repo}/tar.gz/{ref}"
    tmpdir = Path(tempfile.mkdtemp(prefix="adgn-specimen-archive-"))
    tar_path = tmpdir / f"{repo}-{ref}.tar.gz"
    try:
        with urlopen(url) as resp, open(tar_path, "wb") as out:
            out.write(resp.read())
    except (URLError, HTTPError):
        return None
    # Extract
    with tarfile.open(tar_path, "r:gz") as tf:
        tf.extractall(tmpdir)
    # GitHub tarball extracts to repo-ref/ directory
    # Find first directory in tmpdir
    for p in tmpdir.iterdir():
        if p.is_dir():
            return p.resolve()
    return None


def run_critic(manifest_path: Path, cfg: RunnerConfig) -> int:
    specimen_dir = manifest_path.parent
    manifest = load_manifest(manifest_path)

    # Resolve root path from a fresh, private working dir
    if isinstance(manifest.source, GitHubSource):
        # Try public tarball; fallback to git clone via https
        root = try_download_github_archive(manifest.source.org, manifest.source.repo, manifest.source.ref)
        if root is None:
            url = f"https://github.com/{manifest.source.org}/{manifest.source.repo}.git"
            root = fresh_git_checkout_url(url, manifest.source.ref, cfg.gitconfig)
    elif isinstance(manifest.source, GitSource):
        root = try_download_github_archive(*parse_github_owner_repo(manifest.source.url) or (None, None), manifest.source.ref) if parse_github_owner_repo(manifest.source.url) else None
        if root is None:
            root = fresh_git_checkout_url(manifest.source.url, manifest.source.ref, cfg.gitconfig)
    elif isinstance(manifest.source, LocalSource):
        root = fresh_local_copy((specimen_dir / manifest.source.root))
    else:
        raise RuntimeError(f"Unsupported source type: {type(manifest.source)}")

    scope_text = build_scope_text(manifest.scope.include, manifest.scope.exclude)

    cmd = [
        "adgn-codex-properties",
        "find",
        str(root),
        scope_text,
    ]
    # Always prefer full-auto and skip git repo check for specimen runs
    cmd += ["--full-auto", "--skip-git-repo-check"]
    for p in (cfg.embed_paths or []):
        cmd += ["--embed-path", p]
    if cfg.dry_run:
        cmd.append("--dry-run")
    if cfg.output_json:
        cmd.append("--json")

    print("Running:")
    print(" ", " ".join(f'"{c}"' if " " in c else c for c in cmd))

    proc = subprocess.run(cmd)
    return proc.returncode


def parse_args(argv: List[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Run adgn codex critic against a specimen")
    ap.add_argument("specimen", nargs="?", help="Specimen name (subdir of specimens/), path to a specimen dir, or path to manifest.yaml")
    ap.add_argument("--dry-run", action="store_true", help="Pass --dry-run to critic")
    ap.add_argument("--json", action="store_true", help="Request JSON output from critic (passthrough)")
    ap.add_argument("--embed-path", action="append", dest="embed_paths", help="Extra paths to embed into the prompt")
    ap.add_argument("--gitconfig", help="Path to a gitconfig to use (applies only when falling back to git)")
    return ap.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    ns = parse_args(argv)
    base = find_specimens_base()
    manifest_path = resolve_manifest_arg(ns.specimen, base)
    if manifest_path is None:
        # List and exit
        names = list_specimen_names(base)
        if not names:
            print("No specimens found under:", base, file=sys.stderr)
            return 2
        print("Available specimens:")
        for n in names:
            print(" -", n)
        print("\nUsage: python -m adgn_llm.properties.specimen_runner <specimen-name>|<path-to-specimen>|<path-to-manifest.yaml>")
        return 0

    if not manifest_path.exists():
        print(f"ERROR: manifest not found at {manifest_path}", file=sys.stderr)
        return 2

    # Validate optional gitconfig path early
    gitconfig_path: Optional[str] = None
    if ns.gitconfig is not None:
        p = Path(ns.gitconfig).expanduser().resolve()
        if not p.exists():
            print(f"ERROR: --gitconfig file not found: {p}", file=sys.stderr)
            return 2
        gitconfig_path = str(p)

    cfg = RunnerConfig(dry_run=ns.dry_run, output_json=ns.json, embed_paths=ns.embed_paths, gitconfig=gitconfig_path)
    return run_critic(manifest_path, cfg)


if __name__ == "__main__":
    raise SystemExit(main())
