from __future__ import annotations

from importlib import resources


def load_system_prompt() -> str:
    with resources.as_file(
        resources.files("ember").joinpath("system_prompt.md")
    ) as path:
        return path.read_text(encoding="utf-8")
