from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from adgn_llm.llm_edit import app


@pytest.mark.asyncio
async def test_typer_cli_invokes_execute_without_sys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Prepare a file path and a prompt
    p = tmp_path / "file.txt"
    p.write_text("X\n", encoding="utf-8")
    prompt = "Do a trivial change (mocked; no real API call)"

    # Stub _execute to avoid network calls and to assert arguments
    called = {}

    async def fake_execute(*, file_path: Path, prompt: str, model: str, reasoning_effort, reasoning_summary) -> int:
        called.update(
            {
                "file_path": file_path,
                "prompt": prompt,
                "model": model,
                "reasoning_effort": reasoning_effort,
                "reasoning_summary": reasoning_summary,
            }
        )
        return 0

    from adgn_llm import llm_edit as mod

    monkeypatch.setattr(mod, "_execute", fake_execute)

    # Invoke Typer app via CliRunner (no sys.patch)
    runner = CliRunner()
    result = runner.invoke(app, ["edit", str(p), prompt, "--model", "o4-mini"])  # type: ignore[list-item]

    assert result.exit_code == 0, result.output
    # Ensure our stub was called with parsed arguments
    assert called["file_path"] == p
    assert called["prompt"] == prompt
    assert called["model"] == "o4-mini"
