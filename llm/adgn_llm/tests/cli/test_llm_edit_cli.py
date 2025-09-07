from __future__ import annotations

from pathlib import Path

import pytest
from openai.types.responses import Response
from typer.testing import CliRunner

from adgn_llm.llm_edit import app


def test_typer_cli_invokes_execute_without_sys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Prepare a file path and a prompt
    p = tmp_path / "file.txt"
    p.write_text("X\n", encoding="utf-8")
    prompt = "Do a trivial change (mocked; no real API call)"

    called: dict[str, object] = {}

    from adgn_llm import llm_edit as mod

    class DummyResponses:
        async def create(self, **_: object) -> Response:
            return Response(
                id="dummy",
                created=0,
                created_at=0,
                model="dummy",
                output=[],
                status="completed",
                type="response",
                object="response",
                completion=None,
                metadata=None,
                usage=None,
                parallel_tool_calls=False,
                tool_choice="auto",
                tools=[],
            )

    class DummyOpenAI:
        def __init__(self, *args: object, **kwargs: object) -> None:
            called.update({"client_args": args, "client_kwargs": kwargs})
            self.responses = DummyResponses()

    monkeypatch.setattr(mod.openai, "AsyncOpenAI", DummyOpenAI)

    runner = CliRunner()
    result = runner.invoke(app, [str(p), prompt, "--model", "o4-mini"])  # type: ignore[list-item]

    assert result.exit_code == 0, result.output
    # Ensure arguments were parsed correctly
    assert called.get("client_kwargs") == {}
    assert (p.exists())
