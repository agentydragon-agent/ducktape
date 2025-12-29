from __future__ import annotations

import pygit2

from .core import _diff, _format_name_status, _format_status_porcelain, status_letter_text

# Marker used by git to separate commit message from commented metadata
SCISSORS_MARK = "# ------------------------ >8 ------------------------"

# Cap verbose diff lines under scissors (purely for readability in editor)
MAX_VERBOSE_DIFF_LINES = 3000


def _config_bool(value: str | None) -> bool:
    if value is None:
        return False
    v = value.strip().lower()
    return v in {"1", "true", "yes", "on"}


def build_commit_template(repo: pygit2.Repository, passthru: list[str]) -> str:
    """Assemble a git-like commit template (status + optional verbose diff).

    Mirrors the parts of `git commit` template that are user-facing and helpful:
    - On-branch header
    - Staged changes, unstaged changes, untracked files
    - Scissors marker + optional verbose diff (commented)
    """
    branch = repo.head.shorthand if not repo.head_is_detached else "HEAD detached"
    status_output = _format_status_porcelain(repo)
    template_text = f"""# Please enter the commit message for your changes. Lines starting
# with '#' will be ignored, and an empty message aborts the commit.
#
# On branch {branch}
#
"""
    staged_files = (_format_name_status(repo, include_all=False) or "").splitlines()
    if staged_files:
        template_text += "# Changes to be committed:\n"
        for line in staged_files:
            status, filename = line.split("\t", 1)
            status_text = status_letter_text(status[0])
            template_text += f"#\t{status_text.ljust(12)} {filename}\n"

    # Add unstaged changes if any
    unstaged = (_format_name_status(repo, include_all=True) or "").splitlines()
    if unstaged:
        template_text += """#
# Changes not staged for commit:
#   (use "git add <file>..." to update what will be committed
#   (use "git restore <file>..." to discard changes in working directory
"""
        for line in unstaged:
            status, filename = line.split("\t", 1)
            status_text = status_letter_text(status[0])
            template_text += f"#\t{status_text.ljust(12)} {filename}\n"

    # Add untracked files if any
    untracked = [line[3:] for line in status_output.splitlines() if line.startswith("?? ")]
    if untracked:
        # Blank commented spacer before untracked section (readability)
        template_text += "#\n"
        template_text += """# Untracked files:
#   (use "git add <file>..." to include in what will be committed)
"""
        for filename in untracked:
            template_text += f"#\t{filename}\n"

    # Always add scissors marker; verbose diff may be auto-enabled by git config
    template_text += "#\n"
    template_text += f"""{SCISSORS_MARK}
# Do not modify or remove the line above.
# Everything below it will be ignored.
"""

    # Determine verbose per git semantics: '-v' flag OR commit.verbose=true
    include_verbose = ("-v" in passthru) or ("--verbose" in passthru)
    if not include_verbose:
        # Honor git config commit.verbose when flags are absent
        try:
            cfg_val = repo.config["commit.verbose"]
        except KeyError:
            cfg_val = None
        include_verbose = _config_bool(cfg_val)

    if include_verbose:
        diff_text = _diff(repo, include_all=False).patch or ""
        diff_lines = diff_text.splitlines()
        if len(diff_lines) > MAX_VERBOSE_DIFF_LINES:
            total = len(diff_lines)
            diff_lines = [
                *diff_lines[:MAX_VERBOSE_DIFF_LINES],
                f"# [TRUNCATED: showing first {MAX_VERBOSE_DIFF_LINES} of {total} lines]",
            ]
        # Comment diff lines for readability and to ensure they are ignored even without scissors
        template_text += "\n".join(f"# {ln}" for ln in diff_lines)

    return template_text
