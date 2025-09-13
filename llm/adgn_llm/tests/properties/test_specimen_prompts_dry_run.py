from __future__ import annotations

from pathlib import Path
import re

import pytest

from adgn_llm.properties import cli as props_cli

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
def test_specimen_check_dry_run_renders(allow_general, capsys):
    # Calls specimen-check in dry-run to write prompt to a temp file and print its path
    argv = [
        "specimen-check",
        SPECIMEN_NAME,
        "--dry-run",
    ]
    if allow_general:
        argv.append("--allow-general-findings")
    rc = props_cli.main(argv)
    assert rc == 0
    out = capsys.readouterr().out
    saved = _extract_saved_prompt_path(out)
    text = _read(saved)
    # Header is rendered via _base; begins with a single H1 (# …)
    assert text.splitlines()[0].startswith("# ")
    # Base header renders input schemas for Occurrence/LineRange
    assert "Input Schemas:" in text
    assert "\n- Occurrence\n```json" in text
    assert "\n- LineRange\n```json" in text


def test_specimen_discover_dry_run_renders(capsys):
    rc = props_cli.main(["specimen-discover", SPECIMEN_NAME, "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    saved = _extract_saved_prompt_path(out)
    text = _read(saved)
    assert text.splitlines()[0].startswith("# Discover")
    assert "Only report findings that are NOT already listed" in text
    assert "Input Schemas:" in text


def test_specimen_grade_dry_run_renders(tmp_path: Path, capsys):
    crit = tmp_path / "critique.txt"
    crit.write_text("- example critique item", encoding="utf-8")
    rc = props_cli.main(
        [
            "specimen-grade",
            SPECIMEN_NAME,
            "--critique",
            str(crit),
            "--dry-run",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    saved = _extract_saved_prompt_path(out)
    text = _read(saved)
    assert text.splitlines()[0].startswith("# Grade")
    assert "Canonical findings (positives and negatives):" in text
    assert "Input critique:" in text
