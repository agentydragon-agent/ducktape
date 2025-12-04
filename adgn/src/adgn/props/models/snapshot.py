from __future__ import annotations

from typing import Annotated, Literal, NewType

from pydantic import BaseModel, ConfigDict, Field

from adgn.props.splits import Split


SnapshotSlug = NewType("SnapshotSlug", str)  # Format: "{repo}/{version}" e.g. "ducktape/2025-11-26-00"


class GitSource(BaseModel):
    vcs: Literal["git"]
    url: str
    commit: str  # Full commit SHA for cache validation
    ref: str | None = None  # Optional tag/branch name for convenience


class GitHubSource(BaseModel):
    vcs: Literal["github"]
    org: str
    repo: str
    ref: str


class LocalSource(BaseModel):
    vcs: Literal["local"]
    root: str = "."


Source = Annotated[GitSource | GitHubSource | LocalSource, Field(discriminator="vcs")]


class BundleFilter(BaseModel):
    """Build-time metadata for bundle creation (optional).

    Only needed when regenerating bundles from a source repository.
    Contains the source commit SHA and gitignore-style filters.

    Uses gitignore-style patterns:
    - Trailing slash means directory (e.g., "web/" excludes the web directory)
    - No wildcards needed for "everything under" (e.g., "adgn/" includes all of adgn/)
    """

    source_commit: str  # Full commit SHA in the original source repository to filter from
    include: list[str] | None = None
    exclude: list[str] | None = None


class Snapshot(BaseModel):
    """Snapshot: source code + split assignment (decoupled from issues).

    A snapshot represents a specific version of a repository at a point in time,
    with an assigned train/valid/test split. Issues reference snapshots by slug.
    """

    slug: SnapshotSlug
    split: Split
    source: Source
    bundle: BundleFilter | None = None
    model_config = ConfigDict(extra="forbid")

    @property
    def repo(self) -> str:
        """Extract repo from slug (e.g., 'ducktape/2025-11-26-00' → 'ducktape')"""
        return self.slug.split("/", 1)[0]

    @property
    def version(self) -> str:
        """Extract version from slug (e.g., 'ducktape/2025-11-26-00' → '2025-11-26-00')"""
        return self.slug.split("/", 1)[1]


__all__ = [
    "SnapshotSlug",
    "GitSource",
    "GitHubSource",
    "LocalSource",
    "Source",
    "BundleFilter",
    "Snapshot",
]
