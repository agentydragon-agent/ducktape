"""GitHub interface for managing pull requests and remote operations.

TODO: Consider switching to GitHub Python client libraries / API instead of CLI.
This would be more efficient and robust than subprocess calls with JSON parsing.
Consider using PyGithub or the official GitHub API client.
"""

import os
import subprocess
from typing import List

from github import Github

from ..shared.error_handling import GitHubUnavailableError, handle_github_errors
from ..shared.github_models import PRState, PullRequestList, PullRequestSearch
from ..shared.models import PRStatus


class DisabledGitHubInterface:
    """GitHub interface that returns 'disabled' responses instead of making API calls."""

    def __init__(self, github_repo: str):
        self.github_repo = github_repo

    def pr_list(self) -> List[PullRequestList]:
        """Return empty list when GitHub is disabled."""
        return []

    def pr_search(self, branch: str) -> List[PullRequestSearch]:
        """Return empty list when GitHub is disabled."""
        return []

    def pr_view(self, pr_number: int) -> PRStatus | None:
        """Return None when GitHub is disabled."""
        return None


class GitHubInterface:
    def __init__(self, github_repo: str, token: str | None = None):
        token = token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if not token:
            try:
                token = subprocess.run(
                    ["gh", "auth", "token"], capture_output=True, text=True, check=True
                ).stdout.strip()
            except (FileNotFoundError, subprocess.CalledProcessError):
                # Expected cases: gh not installed or not authenticated
                token = None
            except subprocess.TimeoutExpired:
                # Command hung - this is unexpected, let caller handle it
                raise RuntimeError("GitHub CLI command timed out")
            except (OSError, PermissionError) as e:
                # Unexpected system errors that should be visible
                raise RuntimeError(f"Failed to execute GitHub CLI: {e}")
        self.github_repo = github_repo
        self._gh = Github(token) if token else Github()
        self._repo = None  # Lazy initialization

    def _get_repo(self):
        """Lazy initialization of the GitHub repository object."""
        if self._repo is None:
            try:
                self._repo = self._gh.get_repo(self.github_repo)
            except Exception as e:
                raise GitHubUnavailableError(f"Cannot access GitHub repo {self.github_repo}: {e}")
        return self._repo

    @handle_github_errors
    def pr_list(self) -> List[PullRequestList]:
        repo = self._get_repo()
        pulls = repo.get_pulls(state="all", sort="created", direction="desc")
        return [
            PullRequestList(
                number=pr.number,
                headRefName=pr.head.ref,
                state=PRState(pr.state),
                title=pr.title,
                mergedAt=pr.merged_at,
            )
            for pr in pulls
        ]

    @handle_github_errors
    def pr_search(self, branch_name: str) -> List:
        """Search for PRs by branch name using GitHub search API instead of paginating all PRs."""
        repo = self._get_repo()

        # Use GitHub search API to find PRs by head branch - much more efficient
        search_query = f"repo:{self.github_repo} type:pr head:{branch_name}"

        try:
            # Search for issues/PRs matching the branch
            issues = self._gh.search_issues(search_query)

            result = []
            for issue in issues:
                # Get the actual PR object for full details and return it directly
                pr = repo.get_pull(issue.number)
                result.append(pr)  # Return the PyGithub PR object directly

            return result

        except Exception as e:
            # No fallback - let the error propagate to show the real issue
            import logging

            logger = logging.getLogger(__name__)
            logger.error(f"GitHub search API failed for branch '{branch_name}': {e}")
            raise

    @handle_github_errors
    def pr_view(self, branch_name: str) -> dict[str, str]:
        repo = self._get_repo()
        pr = repo.get_pull(int(branch_name))
        return {"number": str(pr.number), "state": pr.state, "title": pr.title}
