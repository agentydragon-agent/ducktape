"""Helper functions for pygit2-based git operations in tests.

This module provides pygit2 wrappers that replace subprocess git calls in tests,
improving performance and reducing subprocess overhead.

All functions accept pygit2.Repository instances. Use the pygit2_repo fixture
or create Repository instances directly for worktrees.
"""

from pathlib import Path

import pygit2

from .test_data import TestData


def get_workdir(repo: pygit2.Repository) -> Path:
    """Get the working directory path from a Repository."""
    return Path(repo.workdir or repo.path).resolve()


def add_and_commit(
    repo: pygit2.Repository,
    files: dict[str, str],
    message: str,
    *,
    author_name: str | None = None,
    author_email: str | None = None,
) -> pygit2.Oid:
    """Stage files and create a commit using pygit2.

    Args:
        repo: pygit2.Repository instance
        files: Dict of filename -> content to write and stage
        message: Commit message
        author_name: Optional author name (defaults to test data)
        author_email: Optional author email (defaults to test data)

    Returns:
        The commit OID
    """
    repo_path = get_workdir(repo)

    # Write and stage files
    for filename, content in files.items():
        file_path = repo_path / filename
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)
        repo.index.add(filename)

    repo.index.write()

    # Create commit
    tree = repo.index.write_tree()
    signature = pygit2.Signature(
        author_name or TestData.Git.USER_NAME,
        author_email or TestData.Git.USER_EMAIL,
    )

    # Get parent commit(s)
    parents = [repo.head.target] if not repo.head_is_unborn else []

    return repo.create_commit("HEAD", signature, signature, message, tree, parents)


def worktree_exists(repo: pygit2.Repository, worktree_path: Path) -> bool:
    """Check if a worktree exists at the given path using pygit2.

    Args:
        repo: pygit2.Repository instance for the main repository
        worktree_path: Path to check for worktree

    Returns:
        True if worktree exists at path
    """
    for wt_name in repo.list_worktrees():
        wt = repo.lookup_worktree(wt_name)
        if Path(wt.path) == worktree_path:
            return True
    return False


def add_worktree(repo: pygit2.Repository, worktree_path: Path, branch: str) -> None:
    """Add a worktree using pygit2.

    Note: This performs a checkout (unlike git worktree add --no-checkout).
    For no-checkout worktrees, use subprocess or git_run.

    Args:
        repo: pygit2.Repository instance for the main repository
        worktree_path: Path where worktree should be created
        branch: Branch name for the worktree
    """
    # Get or create branch reference
    branch_ref = repo.lookup_branch(branch)
    if branch_ref is None:
        # Create branch from HEAD
        commit = repo.head.peel(pygit2.Commit)
        branch_ref = repo.branches.local.create(branch, commit)

    # Add worktree - name is typically the last component of the path
    worktree_name = worktree_path.name
    repo.add_worktree(worktree_name, str(worktree_path), branch_ref)


def get_commit_messages(repo: pygit2.Repository, count: int = 10) -> list[str]:
    """Get recent commit messages using pygit2.

    Args:
        repo: pygit2.Repository instance
        count: Maximum number of commits to return

    Returns:
        List of commit messages (most recent first)
    """
    if repo.head_is_unborn:
        return []

    messages = []
    for commit in repo.walk(repo.head.target, pygit2.GIT_SORT_TIME):
        messages.append(commit.message.strip())
        if len(messages) >= count:
            break

    return messages
