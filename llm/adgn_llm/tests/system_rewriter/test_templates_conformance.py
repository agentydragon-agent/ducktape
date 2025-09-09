from __future__ import annotations

from pathlib import Path
import pytest

from adgn_llm.system_rewriter.validation import validate_template_file


def _templates_dir() -> Path:
    # Parallel to src/: use the package's templates directory
    from adgn_llm.system_rewriter import run_eval
    return Path(run_eval.__file__).parent / "templates"


def _list_templates() -> list[Path]:
    tdir = _templates_dir()
    files: list[Path] = []
    if tdir.exists():
        for p in tdir.rglob("*.txt"):
            # Skip human READMEs in proposals folders
            if p.name.lower() == "readme.txt":
                continue
            files.append(p)
    return sorted(files)


@pytest.mark.parametrize(
    "tmpl_path",
    _list_templates(),
    ids=lambda p: str(p.relative_to(_templates_dir())) if p.exists() else str(p),
)
def test_template_mustache_markers_present_and_only_once(tmpl_path: Path) -> None:
    # Reuse the production validator for DRY conformance rules
    validate_template_file(tmpl_path)


def test_templates_directory_exists_and_has_files() -> None:
    tdir = _templates_dir()
    assert tdir.exists() and tdir.is_dir(), f"templates dir missing: {tdir}"
    files = _list_templates()
    assert files, f"no template *.txt files found under {tdir}"
