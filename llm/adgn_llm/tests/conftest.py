from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _mini_codex_logdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log_dir = tmp_path / "mini_codex_logs"
    monkeypatch.setenv("MINICODEX_LOG_DIR", str(log_dir))
    yield
