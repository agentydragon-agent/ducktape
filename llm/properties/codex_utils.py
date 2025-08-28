#!/usr/bin/env python3
"""Shared utilities for Codex runner scripts.

Assumes the TypeScript codex-tui CLI is installed and available as `codex`.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Iterable

import pyperclip  # Hard dependency for --copy-prompt


def ensure_dir(path: Path) -> None:
    if not path.is_dir():
        raise SystemExit(f"Error: WORKDIR does not exist or is not a directory: {path}")


def git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=str(cwd), text=True, capture_output=True)


def determine_merge_base(workdir: Path, upstream_ref: str) -> str:
    if not upstream_ref:
        raise SystemExit("Error: --upstream-ref is required (e.g., origin/main)")
    cp = git("merge-base", upstream_ref, "HEAD", cwd=workdir)
    if cp.returncode == 0 and cp.stdout.strip():
        return cp.stdout.strip()
    raise SystemExit(
        f"Error: could not determine merge base against {upstream_ref}. Ensure the ref exists and is fetched."
    )


def resolve_properties_dir(default_base: Path, override: str | None) -> Path:
    p = Path(override).expanduser().resolve() if override else (default_base / "properties").resolve()
    if not p.is_dir():
        raise SystemExit(f"Error: properties directory not found: {p}")
    return p


def read_all_properties_text(properties_dir: Path) -> str:
    # Support nested categories (e.g., python/, markdown/) under properties_dir
    prop_files = sorted(properties_dir.rglob("*.md"))
    if not prop_files:
        raise SystemExit(f"No properties found in {properties_dir}")
    parts: list[str] = []
    for pf in prop_files:
        rel = pf.relative_to(properties_dir)
        parts.append(f"# {rel.as_posix()}\n{pf.read_text(encoding='utf-8')}")
    return "\n\n".join(parts)


def build_codex_cmd(
    *,
    model: str,
    workdir: Path,
    sandbox: str,
    skip_git_repo_check: bool = False,
    full_auto: bool = False,
    extra_configs: Iterable[str] | None = None,
) -> list[str]:
    cmd: list[str] = ["codex", "exec", "-m", model, "-s", sandbox, "-C", str(workdir)]
    if extra_configs:
        for cfg in extra_configs:
            cmd.extend(["-c", cfg])
    if full_auto:
        cmd.append("--full-auto")
    if skip_git_repo_check:
        cmd.append("--skip-git-repo-check")
    return cmd


def copy_to_clipboard(text: str) -> None:
    pyperclip.copy(text)


def print_dry_run(cmd: list[str], prompt: str) -> None:
    print("\n# Dry run: would execute command:\n" + " ".join(map(str, cmd)))
    print("\n# Prompt (full):\n")
    print(prompt)
