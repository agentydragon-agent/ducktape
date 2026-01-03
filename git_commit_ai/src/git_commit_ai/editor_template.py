from __future__ import annotations

from dataclasses import asdict, dataclass
from importlib import resources

import pygit2
from mako.template import Template

from .core import _diff, _format_name_status, _format_status_porcelain, status_letter_text

# Marker used by git to separate commit message from commented metadata (without # prefix)
SCISSORS_MARK = "------------------------ >8 ------------------------"

# Cap verbose diff lines under scissors (purely for readability in editor)
MAX_VERBOSE_DIFF_LINES = 3000


def _config_bool(value: str | None) -> bool:
    if value is None:
        return False
    v = value.strip().lower()
    return v in {"1", "true", "yes", "on"}


@dataclass
class EditorTemplateData:
    """Data passed to the editor comment template."""

    user_context: str | None
    previous_message: str | None
    stats_line: str
    branch: str
    staged_files: list[tuple[str, str]]  # (status_text, filename)
    unstaged_files: list[tuple[str, str]]  # (status_text, filename)
    untracked_files: list[str]
    scissors_mark: str
    verbose_diff: list[str] | None


def gather_template_data(
    repo: pygit2.Repository,
    passthru: list[str],
    *,
    user_context: str | None = None,
    previous_message: str | None = None,
    stats_line: str = "",
) -> EditorTemplateData:
    """Gather all data needed for the editor template from the repository."""
    branch = repo.head.shorthand if not repo.head_is_detached else "HEAD detached"
    status_output = _format_status_porcelain(repo)

    # Parse staged files
    staged_files: list[tuple[str, str]] = []
    for line in (_format_name_status(repo, include_all=False) or "").splitlines():
        status, filename = line.split("\t", 1)
        status_text = status_letter_text(status[0])
        staged_files.append((status_text, filename))

    # Parse unstaged files
    unstaged_files: list[tuple[str, str]] = []
    for line in (_format_name_status(repo, include_all=True) or "").splitlines():
        status, filename = line.split("\t", 1)
        status_text = status_letter_text(status[0])
        unstaged_files.append((status_text, filename))

    # Parse untracked files
    untracked_files = [line[3:] for line in status_output.splitlines() if line.startswith("?? ")]

    # Determine verbose diff
    include_verbose = ("-v" in passthru) or ("--verbose" in passthru)
    if not include_verbose:
        try:
            cfg_val = repo.config["commit.verbose"]
        except KeyError:
            cfg_val = None
        include_verbose = _config_bool(cfg_val)

    verbose_diff: list[str] | None = None
    if include_verbose:
        diff_text = _diff(repo, include_all=False).patch or ""
        diff_lines = diff_text.splitlines()
        if len(diff_lines) > MAX_VERBOSE_DIFF_LINES:
            total = len(diff_lines)
            diff_lines = [
                *diff_lines[:MAX_VERBOSE_DIFF_LINES],
                f"[TRUNCATED: showing first {MAX_VERBOSE_DIFF_LINES} of {total} lines]",
            ]
        verbose_diff = diff_lines

    return EditorTemplateData(
        user_context=user_context,
        previous_message=previous_message,
        stats_line=stats_line,
        branch=branch,
        staged_files=staged_files,
        unstaged_files=unstaged_files,
        untracked_files=untracked_files,
        scissors_mark=SCISSORS_MARK,
        verbose_diff=verbose_diff,
    )


def render_comment_section(data: EditorTemplateData) -> str:
    """Render the comment section using the Mako template.

    The template applies # prefix to the commented section; verbose diff is verbatim.
    """
    template_pkg = resources.files(__package__).joinpath("templates")
    template_text = template_pkg.joinpath("editor_comment.mako").read_text("utf-8")
    return Template(template_text).render(**asdict(data)).strip()


def build_commit_template(repo: pygit2.Repository, passthru: list[str]) -> str:
    """Assemble a git-like commit template (status + optional verbose diff).

    Returns plain text WITHOUT # prefixes - caller applies comment prefix.

    Mirrors the parts of `git commit` template that are user-facing and helpful:
    - On-branch header
    - Staged changes, unstaged changes, untracked files
    - Scissors marker + optional verbose diff
    """
    data = gather_template_data(repo, passthru)
    return render_comment_section(data)
