from __future__ import annotations

from pathlib import Path
import pygit2

from ..shared.protocol import CommitInfo
from .git_manager import GitManager


class RepoStatus:
    def __init__(self, git_manager: GitManager, config):
        self.git_manager = git_manager
        self.config = config

    def summarize_status(self, worktree_path: Path) -> tuple[CommitInfo | None, tuple[int, int], str]:
        repo = self.git_manager.get_repo(worktree_path)
        branch_name = repo.head.shorthand
        commit_info: CommitInfo | None
        try:
            data = self.git_manager.get_commit_info("HEAD", worktree_path)
            commit_info = CommitInfo.model_validate(data)
        except Exception:
            try:
                data = self.git_manager.get_commit_info("HEAD", self.config.main_repo)
                commit_info = CommitInfo.model_validate(data)
            except Exception:
                commit_info = None
        ahead_behind = (0, 0)
        if worktree_path != self.config.main_repo:
            try:
                main_repo = self.git_manager.get_repo(self.config.main_repo)
                local_ref = main_repo.lookup_reference(f"refs/heads/{branch_name}")
                upstream_ref = main_repo.lookup_reference(
                    f"refs/heads/{self.config.upstream_branch}"
                )
                local_id = local_ref.target
                upstream_id = upstream_ref.target
                ahead, behind = main_repo.ahead_behind(local_id, upstream_id)
                ahead_behind = (ahead, behind)
            except Exception:
                ahead_behind = (0, 0)
        return commit_info, ahead_behind, branch_name
