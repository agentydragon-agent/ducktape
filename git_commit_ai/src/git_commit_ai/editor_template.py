from __future__ import annotations

from importlib import resources

import pygit2
from mako.template import Template

# Marker used by git to separate commit message from commented metadata (without # prefix)
SCISSORS_MARK = "------------------------ >8 ------------------------"

# Status flags that indicate a file is staged (not purely untracked)
_STAGED_FLAGS = (
    pygit2.GIT_STATUS_INDEX_NEW
    | pygit2.GIT_STATUS_INDEX_MODIFIED
    | pygit2.GIT_STATUS_INDEX_DELETED
    | pygit2.GIT_STATUS_INDEX_RENAMED
    | pygit2.GIT_STATUS_INDEX_TYPECHANGE
)


def _config_bool(value: str | None) -> bool:
    if value is None:
        return False
    v = value.strip().lower()
    return v in {"1", "true", "yes", "on"}


def render_editor_comment(
    repo: pygit2.Repository,
    passthru: list[str],
    *,
    user_context: str | None = None,
    previous_message: str | None = None,
    stats_line: str = "",
) -> str:
    """Render the editor comment section (status, optional verbose diff)."""
    branch = repo.head.shorthand if not repo.head_is_detached else "HEAD detached"

    # Staged: HEAD → index
    staged_diff = repo.diff(repo.head.target, None, cached=True)
    # Unstaged: index → worktree
    unstaged_diff = repo.diff()

    # Untracked files: WT_NEW but not staged
    untracked_files = [
        path
        for path, flags in repo.status().items()
        if (flags & pygit2.GIT_STATUS_WT_NEW) and not (flags & _STAGED_FLAGS)
    ]

    # Determine verbose diff
    include_verbose = ("-v" in passthru) or ("--verbose" in passthru)
    if not include_verbose:
        try:
            cfg_val = repo.config["commit.verbose"]
        except KeyError:
            cfg_val = None
        include_verbose = _config_bool(cfg_val)

    template_pkg = resources.files(__package__).joinpath("templates")
    template_text = template_pkg.joinpath("editor_comment.mako").read_text("utf-8")
    return (
        Template(template_text)
        .render(
            user_context=user_context,
            previous_message=previous_message,
            stats_line=stats_line,
            branch=branch,
            staged_diff=staged_diff,
            unstaged_diff=unstaged_diff,
            untracked_files=untracked_files,
            scissors_mark=SCISSORS_MARK,
            include_verbose=include_verbose,
        )
        .strip()
    )
