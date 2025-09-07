"""Pydantic models for specimen manifest (algebraic source + scope).

YAML frontmatter example:
  ---
  source:
    # Git repository (GitHub is just a git remote)
    vcs: git
    url: https://github.com/owner/repo.git  # or ssh: git@github.com:owner/repo.git
    ref: <commit|branch|tag>
    # OR local/static file scope
    #   vcs: local
    #   root: .
  scope:
    include:
      - path/glob/**
    exclude:
      - optional/exclude/**
  ---
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field


# Algebraic/discriminated source types
class GitSource(BaseModel):
    vcs: Literal["git"]
    url: str  # https or ssh remote
    ref: str  # commit SHA, tag, or branch


class GitHubSource(BaseModel):
    vcs: Literal["github"]
    org: str
    repo: str
    ref: str  # commit SHA, tag, or branch


class LocalSource(BaseModel):
    vcs: Literal["local"]
    root: str = "."  # local root directory


Source = Annotated[
    GitSource | GitHubSource | LocalSource,
    Field(discriminator="vcs"),
]


class Scope(BaseModel):
    """Scope globs relative to source root (repo root or local root)."""

    include: list[str]
    exclude: list[str] | None = None


class SpecimenManifest(BaseModel):
    """Main frontmatter model."""

    source: Source
    scope: Scope
