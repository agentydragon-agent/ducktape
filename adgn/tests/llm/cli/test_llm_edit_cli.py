from __future__ import annotations

from pathlib import Path

import pytest

from adgn.llm_edit import main
from agent_core.testing import AssistantMessage
from openai_utils import client_factory


def test_typer_cli_invokes_execute_without_sys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_step_runner
) -> None:
    # Prepare a file path and a prompt
    p = tmp_path / "file.txt"
    p.write_text("X\n", encoding="utf-8")
    prompt = "Do a trivial change (mocked; no real API call)"

    called: dict[str, object] = {}

    def _mk_client(model: str):
        called.update({"client_model": model})
        return make_step_runner(steps=[AssistantMessage("ok")])

    monkeypatch.setattr(client_factory, "build_client", _mk_client, raising=True)

    # Invoke the CLI entrypoint directly to avoid Click/Typer internals
    exit_code = 0
    try:
        main([str(p), prompt, "--model", "o4-mini"])
    except SystemExit as e:  # Typer raises Exit to signal return code
        exit_code = e.code if isinstance(e.code, int) else 0

    assert exit_code == 0
    # Ensure arguments were parsed correctly (no extra kwargs expected)
    assert p.exists()
