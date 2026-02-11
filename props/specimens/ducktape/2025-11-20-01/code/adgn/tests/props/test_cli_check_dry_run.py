from __future__ import annotations

from pathlib import Path
import re

from typer.testing import CliRunner

from adgn.props.cli_app.main import app


def _extract_saved_prompt_path(stdout: str) -> Path:
    m = re.search(r"Saved prompt: (\S+) ", stdout)
    assert m, f"did not find Saved prompt path in output:\n{stdout}"
    p = Path(m.group(1))
    assert p.exists(), f"saved prompt path does not exist: {p}"
    return p


def test_cli_check_dry_run_tmp_workdir(tmp_path):
    # Minimal run: check --dry-run on a temp dir
    runner = CliRunner()
    result = runner.invoke(app, ["check", str(tmp_path), "all files under src/**", "--dry-run"])
    assert result.exit_code == 0, result.output
    out = result.output
    saved = _extract_saved_prompt_path(out)
    text = saved.read_text(encoding="utf-8")
    # Header present and schemas rendered (Occurrence/LineRange are the defaults in templates)
    assert text.startswith("# ")
    assert "Input Schemas:" in text
    assert "- Occurrence\n```json" in text
    assert "- LineRange\n```json" in text
