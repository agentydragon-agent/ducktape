from __future__ import annotations

import pygit2

# Shared constants used by backends and CLI
MAX_PROMPT_CONTEXT_CHARS = 100_000  # 100k character cap for AI context block
PAST_COMMITS_MAX_CHARS = 6000
RECENT_COMMITS_FOR_CONTEXT = 30
DIFF_SNIPPET_CHARS = 5000
TRUNCATION_NOTE = "[Context truncated to 100k characters]"


def _join_with_truncation(parts: list[str], max_chars: int, note: str) -> str:
    """Join parts, truncating if needed."""
    result = "".join(parts)
    if len(result) > max_chars:
        return result[:max_chars] + note + "\n"
    return result


def _diff(repo: pygit2.Repository, include_all: bool) -> pygit2.Diff:
    return repo.diff(repo.head.target, None, cached=not include_all)


def _format_name_status(repo: pygit2.Repository, include_all: bool) -> str:
    diff = _diff(repo, include_all)
    lines: list[str] = []
    for d in diff.deltas:
        status_char = d.status_char()
        if status_char in ("A", "D", "M", "T"):
            lines.append(f"{status_char}\t{d.new_file.path if status_char != 'D' else d.old_file.path}")
        elif status_char == "R":
            lines.append(f"{status_char}\t{d.old_file.path}\t{d.new_file.path}")
        else:
            # Other statuses (e.g., copied, ignored) — skip for prompt brevity
            continue
    return "\n".join(lines)


def _format_unified_diff(repo: pygit2.Repository, include_all: bool) -> str:
    return _diff(repo, include_all).patch or ""


# Unified mapping for status letters to human text (commit template rendering)
STATUS_LETTER_TO_TEXT: dict[str, str] = {
    "A": "new file:",
    "M": "modified:",
    "D": "deleted:",
    "R": "renamed:",
    "T": "typechange:",
}


def status_letter_text(letter: str) -> str:
    return STATUS_LETTER_TO_TEXT.get(letter, f"{letter}:")


def has_uncommitted_changes(repo: pygit2.Repository) -> bool:
    """Check if there are any uncommitted changes (staged or unstaged)."""
    return bool(repo.status())


def _format_status_porcelain(repo: pygit2.Repository) -> str:
    """Return a minimal porcelain-like status using pygit2 flags.

    Prints lines of the form 'XY path' and '?? path' for untracked.
    """
    out: list[str] = []
    st = repo.status()
    for path, flags in st.items():
        x = " "
        y = " "
        # Untracked
        if flags & pygit2.GIT_STATUS_WT_NEW and not (
            flags
            & (
                pygit2.GIT_STATUS_INDEX_NEW
                | pygit2.GIT_STATUS_INDEX_MODIFIED
                | pygit2.GIT_STATUS_INDEX_DELETED
                | pygit2.GIT_STATUS_INDEX_RENAMED
                | pygit2.GIT_STATUS_INDEX_TYPECHANGE
            )
        ):
            out.append(f"?? {path}")
            continue
        # Index (X)
        if flags & pygit2.GIT_STATUS_INDEX_NEW:
            x = "A"
        elif flags & pygit2.GIT_STATUS_INDEX_MODIFIED:
            x = "M"
        elif flags & pygit2.GIT_STATUS_INDEX_DELETED:
            x = "D"
        elif flags & pygit2.GIT_STATUS_INDEX_RENAMED:
            x = "R"
        elif flags & pygit2.GIT_STATUS_INDEX_TYPECHANGE:
            x = "T"
        # Worktree (Y)
        if flags & pygit2.GIT_STATUS_WT_MODIFIED:
            y = "M"
        elif flags & pygit2.GIT_STATUS_WT_DELETED:
            y = "D"
        elif flags & pygit2.GIT_STATUS_WT_TYPECHANGE:
            y = "T"
        out.append(f"{x}{y} {path}")
    return "\n".join(out)


def _log_subjects(repo: pygit2.Repository, n: int = 10) -> list[str]:
    """Return up to n raw commit log entries (short hash + full message)."""
    walker = repo.walk(repo.head.target)
    walker.simplify_first_parent()

    out: list[str] = []
    for commit in walker:
        msg = commit.message or ""
        short = str(commit.id)[:7]
        entry = f"{short} {msg}".rstrip("\n") if msg else short
        out.append(entry)
        if len(out) >= n:
            break
    return out


def _build_ai_context(repo: pygit2.Repository, include_all: bool) -> str:
    ns_header = "git diff HEAD --name-status" if include_all else "git diff --cached --name-status"
    diff_header = "git diff HEAD --unified=0" if include_all else "git diff --cached --unified=0"

    parts = [
        "$ git status --porcelain\n",
        _format_status_porcelain(repo) + "\n",
        f"$ {ns_header}\n",
        _format_name_status(repo, include_all) + "\n",
        f"$ git log --no-color -n {RECENT_COMMITS_FOR_CONTEXT} --stat --pretty=format:%h %B\n",
        "\n".join(_log_subjects(repo, RECENT_COMMITS_FOR_CONTEXT)) + "\n",
        f"$ {diff_header}\n",
        _format_unified_diff(repo, include_all) + "\n",
    ]

    return _join_with_truncation(parts, MAX_PROMPT_CONTEXT_CHARS, TRUNCATION_NOTE)


def diffstat(repo: pygit2.Repository, include_all: bool) -> str:
    diff = _diff(repo, include_all)
    # Emulate a minimal --stat: path and change status
    lines: list[str] = []
    for d in diff.deltas:
        status_char = d.status_char()
        if status_char in ("A", "M", "D", "T"):
            path = d.new_file.path if status_char != "D" else d.old_file.path
            lines.append(f"{path} | {status_char}")
        elif status_char == "R":
            lines.append(f"{d.old_file.path} -> {d.new_file.path} | {status_char}")
    return "\n".join(lines)


def build_prompt(repo: pygit2.Repository, diff: str, include_all: bool, previous_message: str | None = None) -> str:
    context = _build_ai_context(repo, include_all)
    if previous_message:
        prompt = f"""Update and refine this existing commit message based on the current changes.

Previous commit message:
{previous_message}

The commit is being amended. Write an updated message that accurately reflects all changes.
Output ONLY the commit message between <message> and </message> tags.
No explanations, no markdown, no signatures. Do NOT include 'Generated with' or 'Co-Authored-By' lines.

Context:
{context}
"""
    else:
        prompt = f"""Write a concise, imperative-mood Git commit message.
Output ONLY the commit message between <message> and </message> tags.
No explanations, no markdown, no signatures. Do NOT include 'Generated with' or 'Co-Authored-By' lines.

Context:
{context}

Example outputs:
<message>
Add user authentication to API endpoints
</message>

<message>
Refactor database connection handling

- Extract connection pool logic into separate module
- Add retry mechanism for transient failures
</message>

Diffstat:
$ {"git diff HEAD --stat" if include_all else "git diff --cached --stat"}

{diffstat(repo, include_all)}
"""
    if len(diff) < DIFF_SNIPPET_CHARS:
        prompt = (
            prompt
            + f"""
Staged diff:

{diff}"""
        )
    else:
        prompt = (
            prompt
            + f"""
Staged diff (first to {DIFF_SNIPPET_CHARS} of {len(diff)} chars)

{diff[:DIFF_SNIPPET_CHARS]}"""
        )
    log_entries = _log_subjects(repo, 10)
    if log_entries:
        block_header = "\n\nPast commits (raw log):\n\n"
        block_body = ""
        for entry in log_entries:
            addition = f"{entry}\n\n"
            if len(prompt + block_header + block_body + addition) > PAST_COMMITS_MAX_CHARS:
                break
            block_body += addition
        if block_body:
            prompt += block_header + block_body.rstrip()
    return prompt
