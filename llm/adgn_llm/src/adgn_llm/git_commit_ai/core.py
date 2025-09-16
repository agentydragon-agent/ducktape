import re
from typing import List

from git import Repo
from git.exc import GitCommandError

# Shared constants used by backends and CLI
MAX_PROMPT_CONTEXT_BYTES = 100 * 1024  # 100 KiB cap for AI context block
PAST_COMMITS_MAX_CHARS = 6000
RECENT_COMMITS_FOR_CONTEXT = 30


def _len_bytes(s: str) -> int:
    return len(s.encode("utf-8"))


def _cap_append(parts: list[str], chunk: str, cap_bytes: int, truncation_note: str) -> bool:
    """Append chunk to parts unless this would exceed cap; returns True if truncated."""
    current_bytes = _len_bytes("".join(parts))
    needed_bytes = _len_bytes(chunk)
    if current_bytes + needed_bytes >= cap_bytes:
        remaining_bytes = cap_bytes - current_bytes
        if remaining_bytes > 0:
            parts.append(
                chunk.encode("utf-8")[:remaining_bytes].decode(
                    "utf-8",
                    errors="ignore",
                ),
            )
        parts.append(truncation_note + "\n")
        return True
    parts.append(chunk)
    return False


def _build_ai_context(repo: Repo, include_all: bool) -> str:
    parts: list[str] = []
    try:
        parts.append("$ git status --porcelain\n")
        status_out = repo.git.status("--porcelain") + "\n"
        _cap_append(parts, status_out, MAX_PROMPT_CONTEXT_BYTES, "[Context truncated to 100 KiB]")
    except GitCommandError:
        parts.append("[Could not retrieve git status]\n")

    try:
        ns_cmd = "git diff HEAD --name-status" if include_all else "git diff --cached --name-status"
        parts.append(f"$ {ns_cmd}\n")
        ns_out = (
            repo.git.diff("HEAD", "--name-status") if include_all else repo.git.diff("--cached", "--name-status")
        ) + "\n"
        _cap_append(parts, ns_out, MAX_PROMPT_CONTEXT_BYTES, "[Context truncated to 100 KiB]")
    except GitCommandError:
        parts.append("[Could not compute name-status]\n")

    parts.append(
        f"$ git log --no-color -n {RECENT_COMMITS_FOR_CONTEXT} --stat --pretty=format:%h %s\n",
    )
    try:
        log_out = (
            repo.git.log(
                "--no-color",
                f"-n{RECENT_COMMITS_FOR_CONTEXT}",
                "--stat",
                "--pretty=format:%h %s",
            )
            + "\n"
        )
        _cap_append(parts, log_out, MAX_PROMPT_CONTEXT_BYTES, "[Context truncated to 100 KiB]")
    except GitCommandError:
        parts.append("[Could not retrieve recent commits]\n")

    try:
        diff_cmd = "git diff HEAD --unified=0" if include_all else "git diff --cached --unified=0"
        parts.append(f"$ {diff_cmd}\n")
        diff_out = (
            repo.git.diff("HEAD", "--unified=0") if include_all else repo.git.diff("--cached", "--unified=0")
        ) + "\n"
        _cap_append(parts, diff_out, MAX_PROMPT_CONTEXT_BYTES, "[Context truncated to 100 KiB]")
    except GitCommandError:
        parts.append("[Could not compute diff]\n")

    out = "".join(parts)
    if _len_bytes(out) > MAX_PROMPT_CONTEXT_BYTES:
        out = out.encode("utf-8")[:MAX_PROMPT_CONTEXT_BYTES].decode("utf-8", errors="ignore")
        out += "\n[Context truncated to 100 KiB]\n"
    return out


def diffstat(repo: Repo, passthru: List[str]) -> str:
    if "-a" in passthru or "--all" in passthru:
        return repo.git.diff("HEAD", "--stat")
    return repo.git.diff("--cached", "--stat")


def build_prompt(repo: Repo, diff: str, passthru: list[str], previous_message: str | None = None) -> str:
    include_all = ("-a" in passthru) or ("--all" in passthru)
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

{diffstat(repo, passthru)}
"""
    if len(diff) < 5000:
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
Staged diff (first to 5000 of {len(diff)} chars)

{diff[:5000]}"""
        )
    # Past commits (subjects only)
    for i, commit in enumerate(repo.iter_commits("HEAD", max_count=10)):
        new_prompt = prompt
        if i == 0:
            new_prompt += """\n\nPast commits (subjects):\n\n"""
        raw_msg = commit.message
        if isinstance(raw_msg, bytes):
            subj = raw_msg.decode(errors="replace").split("\n\n", 1)[0]
        else:
            subj = raw_msg.split("\n\n", 1)[0]
        new_prompt += f"- {subj}\n"
        if len(new_prompt) > PAST_COMMITS_MAX_CHARS:
            break
        prompt = new_prompt
    return prompt


def _extract_message_from_text(text: str) -> str:
    if match := re.search(r"<message>\s*(.*?)\s*</message>", text, re.DOTALL):
        return match.group(1).strip()
    return text.strip()
