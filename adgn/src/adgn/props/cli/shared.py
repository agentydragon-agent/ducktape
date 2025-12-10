"""Shared CLI utilities for adgn-properties commands."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
import tempfile

import tiktoken
import typer

from adgn.props.models.critic_scopes import AllFilesScope, CriticScopeSpec, ExplicitFileScope
from adgn.props.runs_context import format_timestamp_session


@dataclass(frozen=True)
class BuildOptions:
    sandbox: str
    skip_git_repo_check: bool
    full_auto: bool
    extra_configs: list[str] | None = None


def save_prompt_to_tmp(stem: str, text: str) -> Path:
    """Save prompt text under the system temp dir and print a short summary.

    File name: <stem>_<ts>.md. Prints an approximate token count using tiktoken.
    """
    tmpdir = Path(tempfile.gettempdir()) / "adgn_codex_prompts"
    tmpdir.mkdir(parents=True, exist_ok=True)
    ts = format_timestamp_session()
    outfile = tmpdir / f"{stem}_{ts}.md"
    outfile.write_text(text, encoding="utf-8")
    tokens = len(tiktoken.get_encoding("cl100k_base").encode(text))
    print(f"Saved prompt: {outfile} (approx tokens: {tokens})")
    return outfile


def build_cmd(model: str, workdir: Path, opts: BuildOptions) -> list[str]:
    cmd: list[str] = ["codex", "exec", "--model", model, "--sandbox", opts.sandbox, "-C", str(workdir)]
    if opts.extra_configs:
        for c in opts.extra_configs:
            cmd.extend(["-c", c])
    if opts.full_auto:
        cmd.append("--full-auto")
    if opts.skip_git_repo_check:
        cmd.append("--skip-git-repo-check")
    return cmd


def filter_files(all_files: Mapping[Path, object], requested_files: list[str] | None) -> CriticScopeSpec:
    """Filter available files to requested subset, with validation.

    Args:
        all_files: All available files from snapshot
        requested_files: Optional list of relative paths to filter to

    Returns:
        AllFilesScope if no filter requested, otherwise ExplicitFileScope with validated paths

    Raises:
        typer.Exit: If requested files are invalid or not found
    """
    # No filter → return AllFilesScope sentinel for downstream resolution
    if requested_files is None:
        return AllFilesScope()

    # Validate requested files exist (work with Path internally)
    available: set[Path] = set(all_files.keys())
    requested_set: set[Path] = {Path(f) for f in requested_files}
    invalid: set[Path] = requested_set - available

    if invalid:
        typer.echo("Error: The following files are not in the snapshot:", err=True)
        for f in sorted(str(p) for p in invalid):
            typer.echo(f"  - {f}", err=True)
        typer.echo(f"\nAvailable files ({len(all_files)}):", err=True)
        for f in sorted(str(p) for p in all_files)[:10]:
            typer.echo(f"  - {f}", err=True)
        if len(all_files) > 10:
            typer.echo(f"  ... and {len(all_files) - 10} more", err=True)
        raise typer.Exit(1)

    # Convert validated Path set to ExplicitFileScope
    validated: set[Path] = requested_set & available
    return ExplicitFileScope(files=[str(p) for p in sorted(validated)])
