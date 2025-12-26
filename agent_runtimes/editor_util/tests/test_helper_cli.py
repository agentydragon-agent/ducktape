from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from editor_util.cli import submit_app as app

runner = CliRunner()


def test_helper_missing_env_exits_nonzero(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Clear env to ensure missing vars
    monkeypatch.delenv("MCP_SERVER_URL", raising=False)
    monkeypatch.delenv("MCP_SERVER_TOKEN", raising=False)
    result = runner.invoke(app, ["read-input"])
    assert result.exit_code != 0


def test_helper_unknown_command() -> None:
    result = runner.invoke(app, ["bogus"])
    assert result.exit_code != 0
