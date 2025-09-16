from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


# Specimen schema (v2): source/scope live alongside items in Jsonnet docs
class GitSource(BaseModel):
    vcs: Literal["git"]
    url: str
    ref: str


class GitHubSource(BaseModel):
    vcs: Literal["github"]
    org: str
    repo: str
    ref: str


class LocalSource(BaseModel):
    vcs: Literal["local"]
    root: str = "."


Source = Annotated[GitSource | GitHubSource | LocalSource, Field(discriminator="vcs")]


class Scope(BaseModel):
    include: list[str]
    exclude: list[str] | None = None


class SpecimenDoc(BaseModel):
    """Unified specimen document (v2): source/scope and items (Jsonnet-only).

    Note: issues are loaded separately from issues/*.libsonnet files. We keep
    `items` as a generic list to avoid cross-module type cycles with Issue.
    """

    source: Source
    scope: Scope
    model_config = ConfigDict(extra="forbid")
