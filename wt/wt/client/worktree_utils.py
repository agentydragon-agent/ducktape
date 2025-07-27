"""Direct worktree utility functions for CLI handlers."""

import os
import shlex
from pathlib import Path

from ..shared.git_interface import GitInterface


def get_worktree_path(config, name: str) -> Path:
    """Get path for a worktree by name."""
    return config.worktrees_dir_resolved / name


def require_worktree_exists(config, name: str) -> Path:
    """Require that a worktree exists and return its path."""
    worktree_path = get_worktree_path(config, name)
    if not worktree_path.exists():
        raise RuntimeError(f"Worktree '{name}' does not exist")
    return worktree_path


def get_current_worktree_info(config) -> tuple[Path | None, str | None]:
    """Get current worktree information."""
    cwd = Path.cwd()

    # Check if we're in the main repo
    main_repo = config.main_repo_resolved
    if cwd.is_relative_to(main_repo):
        if cwd == main_repo:
            return main_repo, None

        # Try to get relative path from main repo
        try:
            rel_path = cwd.relative_to(main_repo)
            return main_repo, str(rel_path)
        except ValueError:
            pass

    # Check if we're in a worktree directory
    worktrees_dir = config.worktrees_dir_resolved
    if cwd.is_relative_to(worktrees_dir):
        # Find the worktree root
        for parent in [cwd] + list(cwd.parents):
            if parent.parent == worktrees_dir:
                # This is a worktree root
                try:
                    rel_path = cwd.relative_to(parent)
                    return parent, str(rel_path) if str(rel_path) != "." else None
                except ValueError:
                    return parent, None

    return None, None


def resolve_path(config, worktree_name: str | None, path_spec: str) -> Path:
    """Resolve a path specification within a worktree."""
    if worktree_name:
        # Path in specified worktree
        target_path = require_worktree_exists(config, worktree_name)
    else:
        # Path in current worktree
        current_wt, _ = get_current_worktree_info(config)
        if not current_wt:
            raise RuntimeError("Not in a worktree")
        target_path = current_wt

    # Resolve the path specification
    if path_spec.startswith("/"):
        # Absolute path within worktree
        return target_path / path_spec.lstrip("/")
    elif path_spec.startswith("./"):
        # Relative path from current location within worktree
        current_wt, rel_path = get_current_worktree_info(config)
        if current_wt != target_path:
            raise RuntimeError("Cannot use relative path for different worktree")

        # Get current position within the worktree
        if rel_path:
            current_dir = target_path / rel_path
        else:
            current_dir = target_path

        return (current_dir / path_spec).resolve()
    else:
        # Treat as absolute path within worktree
        return target_path / path_spec


def emit_cd_command(dest_repo: Path, config) -> None:
    """Emit a cd command for shell execution."""
    from ..shared.shell_utils import emit_command
    
    # Try to preserve relative path when switching between worktrees
    current_wt, rel_path = get_current_worktree_info(config)

    if rel_path and current_wt:
        # Try to preserve the relative path in the new worktree
        target_subpath = dest_repo / rel_path
        if target_subpath.exists() and target_subpath.is_dir():
            dest_path = target_subpath
        else:
            dest_path = dest_repo
    else:
        dest_path = dest_repo

    emit_command(f"cd {shlex.quote(str(dest_path))}")


def create_worktree(
    config, name: str, source_worktree: Path | None = None, from_default: bool = True
) -> Path:
    """Create a new worktree."""
    from ..server.git_manager import GitRepositoryManager
    from ..shared.error_handling import validate_worktree_name

    validate_worktree_name(name)

    target_path = config.worktrees_dir_resolved / name

    if target_path.exists():
        raise RuntimeError(f"Worktree '{name}' already exists")

    # Create git interface
    git = GitInterface(config.main_repo_resolved, config.github_repo)
    manager = GitRepositoryManager()

    if source_worktree:
        # Copy from existing worktree
        if not source_worktree.exists():
            raise RuntimeError(f"Source worktree does not exist: {source_worktree}")

        # Get the branch of the source worktree
        try:
            # Find the branch for this worktree path
            worktree_list = git.parse_worktree_list(git.worktree_list())
            source_branch = None
            for wt_path, wt_branch in worktree_list:
                if wt_path.resolve() == source_worktree.resolve() and wt_branch:
                    source_branch = wt_branch
                    break

            if not source_branch:
                raise RuntimeError(
                    f"Cannot determine branch for source worktree: {source_worktree}"
                )

            # Create new branch from source
            new_branch = f"{config.branch_prefix}{name}"
            git.branch_create(new_branch, source_branch)
            git.worktree_add(str(target_path), new_branch)
        except Exception as e:
            raise RuntimeError(f"Failed to copy worktree: {e}") from e
    else:
        # Create from master/default branch
        try:
            # Get the default branch
            default_branch = manager.get_default_branch(config.main_repo_resolved)
            new_branch = f"{config.branch_prefix}{name}"

            if from_default:
                git.branch_create(new_branch, config.default_worktree_base_branch)
            else:
                git.branch_create(new_branch, "HEAD")

            git.worktree_add(str(target_path), new_branch)
        except Exception as e:
            raise RuntimeError(f"Failed to create worktree: {e}") from e

    return target_path


async def remove_worktree(config, name: str, force: bool = False) -> None:
    """Remove a worktree."""
    worktree_path = config.worktrees_dir_resolved / name
    if not worktree_path.exists():
        raise RuntimeError(f"Worktree '{name}' does not exist at {worktree_path}")

    # Create git interface
    git = GitInterface(config.main_repo_resolved, config.github_repo)

    try:
        # Use git worktree remove
        git.worktree_remove(str(worktree_path), force=force)
    except Exception as e:
        raise RuntimeError(f"Failed to remove worktree: {e}") from e
