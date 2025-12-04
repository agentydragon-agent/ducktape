from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from adgn.props.ids import SnapshotSlug, split_snapshot_slug
from adgn.props.splits import Split


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


class SnapshotDoc(BaseModel):
    """Snapshot document: source, bundle filters, and split assignment.

    This is the schema for entries in snapshots.yaml. Issues are loaded separately
    from *.libsonnet files in the snapshot directory.

    Bundle is optional - only required for snapshots that use git bundles.
    Split is required - every snapshot must be assigned to train/valid/test.
    """

    source: Source
    split: Split = Field(description="Train/valid/test split assignment for this snapshot")
    bundle: BundleFilter | None = None
    model_config = ConfigDict(extra="forbid")


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

    def _repo_version(self) -> tuple[str, str]:
        """Split slug into repo and version components.

        Returns:
            Tuple of (repo, version) e.g., ('ducktape', '2025-11-26-00')
        """
        return split_snapshot_slug(self.slug)

    @property
    def repo(self) -> str:
        """Extract repo from slug (e.g., 'ducktape/2025-11-26-00' → 'ducktape')"""
        return self._repo_version()[0]

    @property
    def version(self) -> str:
        """Extract version from slug (e.g., 'ducktape/2025-11-26-00' → '2025-11-26-00')"""
        return self._repo_version()[1]


__all__ = [
    "BundleFilter",
    "GitHubSource",
    "GitSource",
    "LocalSource",
    "Snapshot",
    "SnapshotDoc",
    "SnapshotSlug",
    "Source",
]
