from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _mini_codex_logs(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure MiniCodex writes logs into the per-test tmpdir."""
    log_dir = tmp_path / "mini_codex_logs"
    monkeypatch.setenv("MINICODEX_LOG_DIR", str(log_dir))
    yield
