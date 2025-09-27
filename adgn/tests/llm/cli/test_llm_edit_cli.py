from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from adgn.llm import llm_edit as mod
from adgn.llm.llm_edit import app


def test_typer_cli_invokes_execute_without_sys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    assistant_response_factory,
) -> None:
    # Prepare a file path and a prompt
    p = tmp_path / "file.txt"
    p.write_text("X\n", encoding="utf-8")
    prompt = "Do a trivial change (mocked; no real API call)"

    called: dict[str, object] = {}

    def _mk_client(model: str):
        called.update({"client_model": model})
        from adgn.llm.openai_utils.model import FakeOpenAIModel

        return FakeOpenAIModel([assistant_response_factory("o4-mini", "ok")])

    monkeypatch.setattr(mod, "_make_openai_client", _mk_client, raising=True)

    runner = CliRunner()
    result = runner.invoke(app, [str(p), prompt, "--model", "o4-mini"])  # type: ignore[list-item]

    assert result.exit_code == 0, result.output
    # Ensure arguments were parsed correctly (no extra kwargs expected)
    assert p.exists()
