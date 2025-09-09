from __future__ import annotations

import importlib.resources as res
from pathlib import Path
from typing import Iterator


def validate_template_file(template_path: Path) -> None:
    """Fail fast if template file is unreadable or missing required placeholders.

    Required placeholders (mustache-style):
      - {{toolsBlob}}
      - {{envGitBlobs}}
      - {{modelLine}}
      - {{mcpSection}}
    """
    if not isinstance(template_path, Path):
        raise ValueError("template_path must be a pathlib.Path")
    if not template_path.exists() or not template_path.is_file():
        raise FileNotFoundError(f"Template not found or not a file: {template_path}")
    text = template_path.read_text(encoding="utf-8")

    required = ("{{toolsBlob}}", "{{envGitBlobs}}", "{{modelLine}}", "{{mcpSection}}")
    missing = [m for m in required if m not in text]
    if missing:
        raise RuntimeError(
            "Invalid template: missing required placeholders: "
            + ", ".join(missing)
            + " — expected mustache markers like {{toolsBlob}}."
        )


def iter_templates() -> Iterator[tuple[str, str]]:
    """Yield (relative_name, text) for all packaged templates/*.txt files.

    Traverses the installed package resources under adgn_llm.system_rewriter.templates
    so it works from sdist/wheel installs and zipped packages.
    """
    root = res.files(__name__)

    def _walk(dir_entry, prefix: str = "") -> Iterator[tuple[str, str]]:
        for child in dir_entry.iterdir():
            name = f"{prefix}{child.name}"
            if child.is_dir():
                yield from _walk(child, f"{name}/")
            else:
                if name.endswith(".txt"):
                    text = child.read_text(encoding="utf-8")
                    yield name, text

    return _walk(root, "")


def load_known_templates() -> dict[str, str]:
    """Return mapping of template content (full text) -> relative template name.

    Values look like "current_effective_template.txt" or "proposals/foo.txt".
    """
    mapping: dict[str, str] = {}
    for rel_name, text in iter_templates():
        mapping[text] = rel_name
    return mapping
