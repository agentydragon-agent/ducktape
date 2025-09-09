from __future__ import annotations

from pathlib import Path
import pytest

from adgn_llm.system_rewriter.templates import iter_templates, validate_template_text


def _templates_dir() -> Path:
    # Use package templates directory (for legacy path-based checks)
    from adgn_llm.system_rewriter import run_eval

    return Path(run_eval.__file__).parent / "templates"


def _iter_templates_from_package() -> list[tuple[str, str]]:
    # Reuse production loader to avoid duplicating file walking logic
    out: list[tuple[str, str]] = []
    for rel_name, text in iter_templates():
        if rel_name.lower().endswith("readme.txt"):
            continue
        out.append((rel_name, text))
    return sorted(out, key=lambda t: t[0])


@pytest.mark.parametrize(
    "rel_name, text",
    _iter_templates_from_package(),
    ids=lambda t: t[0],
)
def test_template_mustache_markers_present_and_only_once(rel_name: str, text: str) -> None:
    # Reuse production validator over text to avoid path handling duplication
    validate_template_text(text)


def test_templates_exist_and_are_discoverable() -> None:
    items = _iter_templates_from_package()
    assert items, "no packaged template *.txt files discovered via iter_templates()"
