from __future__ import annotations

import shutil

import pytest


@pytest.fixture(autouse=True)
def _sandboxer_require_sandbox_exec() -> None:
    if not shutil.which("sandbox-exec"):
        pytest.skip("sandbox-exec not found on PATH")
