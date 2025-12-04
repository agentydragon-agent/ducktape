from __future__ import annotations

from pathlib import Path
import re

import pytest
from typer.testing import CliRunner

from adgn.props.cli_app.main import app

SPECIMEN_NAME = "ducktape/2025-11-20-00"


def _extract_saved_prompt_path(stdout: str) -> Path:
    m = re.search(r"Prompt saved to: (\S+)", stdout)
    assert m, f"did not find Saved prompt path in output:\n{stdout}"
    p = Path(m.group(1))
    assert p.exists(), f"saved prompt path does not exist: {p}"
    return p


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("allow_general", [False, True])
def test_run_specimen_dry_run_renders(allow_general):
    # Use the unified runner for dry-run prompt rendering
    argv = ["run", "--snapshot", SPECIMEN_NAME, "--dry-run"]
    # Map 'allow_general' to the 'open' preset; else default 'find'
    if allow_general:
        argv.extend(["--preset", "open"])
    else:
        argv.extend(["--preset", "find"])
    runner = CliRunner()
    result = runner.invoke(app, argv)
    assert result.exit_code == 0, result.output
    out = result.output
    saved = _extract_saved_prompt_path(out)
    text = _read(saved)
    # Header is rendered via _base; begins with a single H1 (# …)
    assert text.splitlines()[0].startswith("# ")
    # Base header renders input schemas for Occurrence/LineRange
    assert "Input Schemas:" in text
    assert "\n- Occurrence\n```json" in text
    assert "\n- LineRange\n```json" in text


def test_run_specimen_discover_dry_run_renders():
    runner = CliRunner()
    result = runner.invoke(app, ["run", "--snapshot", SPECIMEN_NAME, "--preset", "discover", "--dry-run"])
    assert result.exit_code == 0, result.output
    out = result.output
    saved = _extract_saved_prompt_path(out)
    text = _read(saved)
    assert text.splitlines()[0].startswith("# Discover")
    assert "Only report findings that are NOT already listed" in text
    assert "Input Schemas:" in text


def test_run_specimen_grade_dry_run_renders(tmp_path: Path):
    # For prompt rendering checks, validate that run --dry-run composes schemas.
    runner = CliRunner()
    result = runner.invoke(app, ["run", "--snapshot", SPECIMEN_NAME, "--preset", "find", "--dry-run"])
    assert result.exit_code == 0, result.output
    out = result.output
    saved = _extract_saved_prompt_path(out)
    text = _read(saved)
    assert text.splitlines()[0].startswith("# ")
    assert "Input Schemas:" in text
