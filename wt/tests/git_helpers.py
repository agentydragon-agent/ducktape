"""Helper functions for pygit2-based git operations in tests.

This module provides pygit2 wrappers that replace subprocess git calls in tests,
improving performance and reducing subprocess overhead.

Functions accept either a pygit2.Repository or a Path, with Repository preferred
for efficiency when multiple operations are performed on the same repo.
"""

from pathlib import Path

import pygit2

from .test_data import TestData

# Type alias for flexibility
RepoOrPath = pygit2.Repository | Path


def _get_repo(repo_or_path: RepoOrPath) -> pygit2.Repository:
    """Convert path to Repository if needed."""
    if isinstance(repo_or_path, pygit2.Repository):
        return repo_or_path
    return pygit2.Repository(str(repo_or_path))


def _get_path(repo_or_path: RepoOrPath) -> Path:
    """Get path from Repository or return path directly."""
    if isinstance(repo_or_path, pygit2.Repository):
        return Path(repo_or_path.workdir or repo_or_path.path).resolve()
    return repo_or_path


def add_and_commit(
    repo_or_path: RepoOrPath,
    files: dict[str, str],
    message: str,
    *,
    author_name: str | None = None,
    author_email: str | None = None,
) -> pygit2.Oid:
    """Stage files and create a commit using pygit2.

    Args:
        repo_or_path: pygit2.Repository or Path to the git repository (or worktree)
        files: Dict of filename -> content to write and stage
        message: Commit message
        author_name: Optional author name (defaults to test data)
        author_email: Optional author email (defaults to test data)

    Returns:
        The commit OID
    """
    repo = _get_repo(repo_or_path)
    repo_path = _get_path(repo_or_path)

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


def get_current_branch(repo_or_path: RepoOrPath) -> str:
    """Get the current branch name using pygit2.

    Args:
        repo_or_path: pygit2.Repository or Path to the git repository (or worktree)

    Returns:
        The current branch name (shorthand)
    """
    repo = _get_repo(repo_or_path)
    if repo.head_is_detached:
        return str(repo.head.target)[:8]  # Return short hash for detached HEAD
    return repo.head.shorthand


def list_worktrees(repo_or_path: RepoOrPath) -> list[str]:
    """List all worktree names using pygit2.

    Args:
        repo_or_path: pygit2.Repository or Path to the main git repository

    Returns:
        List of worktree names
    """
    repo = _get_repo(repo_or_path)
    return repo.list_worktrees()


def worktree_paths(repo_or_path: RepoOrPath) -> list[Path]:
    """Get paths of all worktrees using pygit2.

    Args:
        repo_or_path: pygit2.Repository or Path to the main git repository

    Returns:
        List of worktree paths (including main repo)
    """
    repo = _get_repo(repo_or_path)
    repo_path = _get_path(repo_or_path)
    paths = [repo_path]  # Main repo is always a worktree

    for wt_name in repo.list_worktrees():
        wt = repo.lookup_worktree(wt_name)
        paths.append(Path(wt.path))

    return paths


def worktree_exists(repo_or_path: RepoOrPath, worktree_path: Path) -> bool:
    """Check if a worktree exists at the given path using pygit2.

    Args:
        repo_or_path: pygit2.Repository or Path to the main git repository
        worktree_path: Path to check for worktree

    Returns:
        True if worktree exists at path
    """
    repo = _get_repo(repo_or_path)
    for wt_name in repo.list_worktrees():
        wt = repo.lookup_worktree(wt_name)
        if Path(wt.path) == worktree_path:
            return True
    return False


def add_worktree(repo_or_path: RepoOrPath, worktree_path: Path, branch: str) -> None:
    """Add a worktree using pygit2.

    Note: This performs a checkout (unlike git worktree add --no-checkout).
    For no-checkout worktrees, use subprocess or git_run.

    Args:
        repo_or_path: pygit2.Repository or Path to the main git repository
        worktree_path: Path where worktree should be created
        branch: Branch name for the worktree
    """
    repo = _get_repo(repo_or_path)

    # Get or create branch reference
    branch_ref = repo.lookup_branch(branch)
    if branch_ref is None:
        # Create branch from HEAD
        commit = repo.head.peel(pygit2.Commit)
        branch_ref = repo.branches.local.create(branch, commit)

    # Add worktree - name is typically the last component of the path
    worktree_name = worktree_path.name
    repo.add_worktree(worktree_name, str(worktree_path), branch_ref)


def get_commit_messages(repo_or_path: RepoOrPath, count: int = 10) -> list[str]:
    """Get recent commit messages using pygit2.

    Args:
        repo_or_path: pygit2.Repository or Path to the git repository (or worktree)
        count: Maximum number of commits to return

    Returns:
        List of commit messages (most recent first)
    """
    repo = _get_repo(repo_or_path)
    if repo.head_is_unborn:
        return []

    messages = []
    for commit in repo.walk(repo.head.target, pygit2.GIT_SORT_TIME):
        messages.append(commit.message.strip())
        if len(messages) >= count:
            break

    return messages
