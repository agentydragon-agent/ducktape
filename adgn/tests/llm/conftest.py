from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from . import git_repo_utils


@pytest.fixture
def author_name() -> str:
    return "Test User"


@pytest.fixture
def author_email() -> str:
    return "test@example.com"


@pytest.fixture
def temp_repo(author_name: str, author_email: str, tmp_path: Path):
    """Temporary git repository for LLM tests (separate from WT helpers)."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir(parents=True, exist_ok=True)
    return git_repo_utils._init_repo(str(repo_dir), name=author_name, email=author_email)


@pytest.fixture
def repo_helpers() -> dict[str, Callable]:
    """Provide stage/commit helpers to tests without re-defining them inline."""
    return {"stage": git_repo_utils._stage, "commit": git_repo_utils._commit}


@pytest.fixture
def patch_fake_editor(monkeypatch):
    """Patch editor launching to a fake editor that appends comments and scissors.

    Ensures commit message parsing (scissors/comment stripping) is exercised
    without invoking a real editor.
    """

    async def _fake_get_editor() -> str:
        return "fake-editor"

    class _Proc:
        def __init__(self, code: int = 0):
            self._code = code

        async def wait(self) -> int:
            return self._code

    async def _fake_shell(cmd: str, *args, **kwargs) -> _Proc:
        # Extract COMMIT_EDITMSG path (last token)
        commit_path = cmd.rsplit(" ", 1)[-1]
        msg = (
            "\n# editor-added comment (should be stripped)\n"
            "# ------------------------ >8 ------------------------\n"
            "# diff line (commented)\n"
        )
        Path(commit_path).write_text(Path(commit_path).read_text() + msg)
        return _Proc(0)

    monkeypatch.setattr("adgn.git_commit_ai.cli._get_editor", _fake_get_editor)
    monkeypatch.setattr("asyncio.create_subprocess_shell", _fake_shell)
