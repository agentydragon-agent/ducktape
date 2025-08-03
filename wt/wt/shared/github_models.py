import json
import time
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class GitHubError(Exception):
    pass


class PRStatus(Enum):
    MERGED = "MERGED"
    CLOSED = "CLOSED"
    OPEN_MERGEABLE = "OPEN_MERGEABLE"
    OPEN_CONFLICTING = "OPEN_CONFLICTING"
    OPEN_UNKNOWN = "OPEN_UNKNOWN"

    @property
    def is_merged(self) -> bool:
        """Check if the PR is merged."""
        return self == PRStatus.MERGED

    @property
    def is_open(self) -> bool:
        return self.name.startswith("OPEN_")

    @property
    def is_closed(self) -> bool:
        return self == PRStatus.CLOSED

    @property
    def display_text(self) -> str:
        if self == PRStatus.MERGED:
            return "merged"
        if self == PRStatus.CLOSED:
            return "closed"
        if self == PRStatus.OPEN_MERGEABLE:
            return "can merge"
        if self == PRStatus.OPEN_CONFLICTING:
            return "conflict"
        if self == PRStatus.OPEN_UNKNOWN:
            return "open"
        return self.value.lower()


# Legacy enums for backward compatibility
class PRState(Enum):
    OPEN = "open"
    CLOSED = "closed"
    MERGED = "merged"

    @property
    def is_merged(self) -> bool:
        """Check if the PR is merged."""
        return self == PRState.MERGED


class PRMergeability(Enum):
    CONFLICTING = "CONFLICTING"
    UNKNOWN = "UNKNOWN"


class PullRequest(BaseModel):
    number: int
    title: str
    state: PRState
    url: str
    mergeable: PRMergeability | None = None
    merged_at: str | None = Field(None, alias="mergedAt")

    class Config:
        validate_by_name = True


class PullRequestSearch(BaseModel):
    number: int
    title: str
    state: PRState
    url: str


class PullRequestList(BaseModel):
    number: int
    head_ref_name: str = Field(alias="headRefName")
    state: PRState
    title: str
    merged_at: str | None = Field(None, alias="mergedAt")


class PullRequestView(BaseModel):
    number: int
    title: str
    body: str
    state: PRState
    url: str
    mergeable: PRMergeability | None = None
    merged_at: str | None = Field(None, alias="mergedAt")

    class Config:
        validate_by_name = True


class PullRequestCache(BaseModel):
    timestamp: float
    prs: list[PullRequestList]

    @classmethod
    def load(cls, cache_file) -> "PullRequestCache | None":
        if not cache_file.exists():
            return None

        cache_data = json.loads(cache_file.read_text())
        return cls.model_validate(cache_data)

    def save(self, cache_file) -> None:
        cache_file.write_text(self.model_dump_json())

    def should_invalidate(self, cache_expiration: int) -> bool:
        return time.time() - self.timestamp > cache_expiration

    @classmethod
    def get_or_refresh(
        cls,
        cache_file,
        cache_expiration: int,
        github_interface,
    ) -> "PullRequestCache":
        cache = cls.load(cache_file)
        if cache is None or cache.should_invalidate(cache_expiration):
            # No cache or invalid cache - fetch fresh data
            fresh_prs = github_interface.pr_list()
            cache = cls(timestamp=time.time(), prs=fresh_prs)
            cache.save(cache_file)
        return cache


class PRData(BaseModel):
    pr_number: int
    pr_state: PRState
    draft: bool = False
    mergeable: bool | None = None
    merged_at: str | None = None
    additions: int | None = None
    deletions: int | None = None


class GitHubPRResponse(BaseModel):
    """Raw GitHub PR API response data"""

    number: int
    state: str
    title: str
    draft: bool = False
    mergeable: bool | None = None
    merged_at: str | None = None
    additions: int | None = None
    deletions: int | None = None

    @classmethod
    def from_github_pr(cls, pr) -> "GitHubPRResponse":
        """Create from PyGithub PR object"""
        return cls(
            number=pr.number,
            state=pr.state,
            title=pr.title,
            draft=pr.draft,
            mergeable=pr.mergeable,
            merged_at=pr.merged_at.isoformat() if pr.merged_at else None,
            additions=pr.additions,
            deletions=pr.deletions,
        )


class PRInfoRepr(BaseModel):
    branch: str
    pr_data: PRData | None = None
    gh_error: str | None = None


def coerce_prdata(src: Any) -> PRData:
    if isinstance(src, PRData):
        return src
    if isinstance(src, GitHubPRResponse):
        return PRData(
            pr_number=src.number,
            pr_state=PRState(src.state),
            draft=src.draft,
            mergeable=src.mergeable,
            merged_at=src.merged_at,
            additions=src.additions,
            deletions=src.deletions,
        )
    if isinstance(src, dict):
        num = src["pr_number"] if "pr_number" in src else src["number"]
        st = src.get("pr_state")
        state = st if isinstance(st, PRState) else PRState(src["state"])  # type: ignore[arg-type]
        return PRData(
            pr_number=int(num),
            pr_state=state,
            draft=bool(src.get("draft", False)),
            mergeable=src.get("mergeable"),
            merged_at=src.get("merged_at"),
            additions=src.get("additions"),
            deletions=src.get("deletions"),
        )
    raise TypeError("Unsupported PR data type")


class PRInfo(BaseModel):
    branch: str
    pr_data: PRData | None = None
    github_pr: Any | None = None  # Store the actual PyGithub PR object
    gh_error: str | None = None

    class Config:
        arbitrary_types_allowed = True

    def to_repr(self) -> PRInfoRepr:
        return PRInfoRepr(
            branch=self.branch,
            pr_data=self.pr_data,
            gh_error=self.gh_error,
        )
