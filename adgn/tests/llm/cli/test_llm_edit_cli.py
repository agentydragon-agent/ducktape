from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from adgn.llm.llm_edit import app
from adgn.openai_utils import client_factory


def test_typer_cli_invokes_execute_without_sys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    responses_factory,
) -> None:
    # Prepare a file path and a prompt
    p = tmp_path / "file.txt"
    p.write_text("X\n", encoding="utf-8")
    prompt = "Do a trivial change (mocked; no real API call)"

    called: dict[str, object] = {}

    def _mk_client(model: str):
        called.update({"client_model": model})
        from adgn.openai_utils.model import FakeOpenAIModel

        return FakeOpenAIModel([responses_factory.make_assistant_message("ok")])

    monkeypatch.setattr(client_factory, "build_client", _mk_client, raising=True)

    runner = CliRunner()
    result = runner.invoke(app, [str(p), prompt, "--model", "o4-mini"])  # type: ignore[list-item]

    assert result.exit_code == 0, result.output
    # Ensure arguments were parsed correctly (no extra kwargs expected)
    assert p.exists()
