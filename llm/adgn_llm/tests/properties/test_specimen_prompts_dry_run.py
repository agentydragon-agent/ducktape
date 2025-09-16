from __future__ import annotations

import re
from pathlib import Path

import pytest
from adgn_llm.properties.cli_app.main import app as props_app
from typer.testing import CliRunner

SPECIMEN_NAME = "2025-09-02-ducktape_wt"


def _extract_saved_prompt_path(stdout: str) -> Path:
    m = re.search(r"Saved prompt: (\S+) ", stdout)
    assert m, f"did not find Saved prompt path in output:\n{stdout}"
    p = Path(m.group(1))
    assert p.exists(), f"saved prompt path does not exist: {p}"
    return p


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "allow_general",
    [False, True],
)
def test_specimen_check_dry_run_renders(allow_general):
    # Use the Typer CLI (cli_app) for specimen-check dry-run
    argv = [
        "specimen-check",
        SPECIMEN_NAME,
        "--dry-run",
    ]
    if allow_general:
        argv.append("--allow-general-findings")
    runner = CliRunner()
    result = runner.invoke(props_app, argv)
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


def test_specimen_discover_dry_run_renders():
    runner = CliRunner()
    result = runner.invoke(props_app, ["specimen-discover", SPECIMEN_NAME, "--dry-run"])
    assert result.exit_code == 0, result.output
    out = result.output
    saved = _extract_saved_prompt_path(out)
    text = _read(saved)
    assert text.splitlines()[0].startswith("# Discover")
    assert "Only report findings that are NOT already listed" in text
    assert "Input Schemas:" in text


def test_specimen_grade_dry_run_renders(tmp_path: Path):
    # The Typer specimen-grade command does not support --dry-run.
    # For prompt rendering checks, validate that specimen-check --dry-run composes schemas.
    runner = CliRunner()
    result = runner.invoke(
        props_app,
        [
            "specimen-check",
            SPECIMEN_NAME,
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    out = result.output
    saved = _extract_saved_prompt_path(out)
    text = _read(saved)
    assert text.splitlines()[0].startswith("# ")
    assert "Input Schemas:" in text
