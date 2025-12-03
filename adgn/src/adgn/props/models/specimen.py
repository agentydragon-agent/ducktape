from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from adgn.props.splits import Split


# Specimen schema (v2): source/scope live alongside items in Jsonnet docs
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


class SpecimenDoc(BaseModel):
    """Unified specimen document (v2): source, bundle filters, and split assignment.

    Note: issues are loaded separately from issues/*.libsonnet files. We keep
    `items` as a generic list to avoid cross-module type cycles with Issue.

    Bundle is optional - only required for specimens that use git bundles.
    Split is required - every specimen must be assigned to train/valid/test.
    """

    source: Source
    split: Split = Field(description="Train/valid/test split assignment for this specimen")
    bundle: BundleFilter | None = None
    model_config = ConfigDict(extra="forbid")
