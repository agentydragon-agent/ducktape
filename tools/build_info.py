"""Build information parsed from Bazel workspace status at runtime."""

from __future__ import annotations

from functools import lru_cache
from importlib import resources

from pydantic import BaseModel


class BuildInfo(BaseModel, frozen=True):
    commit: str
    commit_time: str


@lru_cache(maxsize=1)
def get_build_info() -> BuildInfo:
    values: dict[str, str] = {}
    try:
        status_text = resources.files(__package__).joinpath("_build_status.txt").read_text()
        for line in status_text.splitlines():
            if " " in line:
                key, value = line.split(" ", 1)
                values[key] = value
    except FileNotFoundError:
        pass
    return BuildInfo(
        commit=values.get("STABLE_BUILD_COMMIT", "dev"), commit_time=values.get("STABLE_BUILD_TIMESTAMP", "dev")
    )
