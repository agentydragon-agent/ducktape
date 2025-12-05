from __future__ import annotations

from pathlib import Path

import pygit2

from adgn.git_commit_ai.editor_template import SCISSORS_MARK, build_commit_template


def _write(repo: pygit2.Repository, relpath: str, content: str) -> Path:
    p = Path(repo.workdir) / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


def test_template_respects_commit_verbose_config(temp_repo: pygit2.Repository, repo_helpers):
    # Seed initial commit
    _write(temp_repo, "README.md", "hello\n")
    repo_helpers["stage"](temp_repo, "README.md")
    repo_helpers["commit"](temp_repo, "init")

    # Stage a new file for commit
    _write(temp_repo, "staged.txt", "content\n")
    repo_helpers["stage"](temp_repo, "staged.txt")

    # Enable commit.verbose via config (no -v flag)
    temp_repo.config["commit.verbose"] = "true"
    t = build_commit_template(temp_repo, [])
    assert SCISSORS_MARK in t
    # Expect commented diff lines for staged changes
    assert "# diff --git" in t

    # Disable commit.verbose; diff lines should not be included
    temp_repo.config["commit.verbose"] = "false"
    t2 = build_commit_template(temp_repo, [])
    assert SCISSORS_MARK in t2
    assert "# diff --git" not in t2


def test_template_sections_for_staged_changes(temp_repo: pygit2.Repository, repo_helpers):
    _write(temp_repo, "a.txt", "a\n")
    repo_helpers["stage"](temp_repo, "a.txt")
    repo_helpers["commit"](temp_repo, "init")

    _write(temp_repo, "b.txt", "b\n")
    repo_helpers["stage"](temp_repo, "b.txt")

    t = build_commit_template(temp_repo, [])
    assert "# Changes to be committed:" in t
    assert "b.txt" in t
    assert SCISSORS_MARK in t


def test_template_sections_for_unstaged_and_untracked(temp_repo: pygit2.Repository, repo_helpers):
    # Init
    _write(temp_repo, "file.txt", "v1\n")
    repo_helpers["stage"](temp_repo, "file.txt")
    repo_helpers["commit"](temp_repo, "init")

    # Make unstaged change
    _write(temp_repo, "file.txt", "v2\n")
    # Create untracked file
    _write(temp_repo, "untracked.txt", "x\n")

    t = build_commit_template(temp_repo, [])
    assert "# Changes not staged for commit:" in t
    assert "file.txt" in t
    assert "# Untracked files:" in t
    assert "untracked.txt" in t
    assert SCISSORS_MARK in t


def test_template_clean_repo(temp_repo: pygit2.Repository, repo_helpers):
    _write(temp_repo, "r.txt", "x\n")
    repo_helpers["stage"](temp_repo, "r.txt")
    repo_helpers["commit"](temp_repo, "init")

    t = build_commit_template(temp_repo, [])
    # Should not show any change sections if clean
    assert "# Changes to be committed:" not in t
    assert "# Changes not staged for commit:" not in t
    assert "# Untracked files:" not in t
    assert SCISSORS_MARK in t
