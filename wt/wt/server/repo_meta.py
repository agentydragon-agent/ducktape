from __future__ import annotations

from pathlib import Path
from typing import Any

from .git_manager import GitManager


class RepoMetaService:
    def __init__(self, git_manager: GitManager, config):
        self.git_manager = git_manager
        self.config = config

    def compute_meta(
        self,
        worktree_path: Path,
    ) -> tuple[dict[str, Any], tuple[int, int], str]:
        repo = self.git_manager.get_repo(worktree_path)
        branch_name = repo.head.shorthand
        commit_info_data = self.git_manager.get_commit_info("HEAD", worktree_path)
        ahead_behind = (0, 0)
        if worktree_path != self.config.main_repo:
            try:
                main_repo = self.git_manager.get_repo(self.config.main_repo)
                ahead, behind = main_repo.ahead_behind(
                    f"refs/heads/{branch_name}",
                    f"refs/heads/{self.config.upstream_branch}",
                )
                ahead_behind = (ahead, behind)
            except Exception:
                ahead_behind = (0, 0)
        return commit_info_data, ahead_behind, branch_name
