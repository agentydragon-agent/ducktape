"""Tests for shim binary resolution."""

import pytest
import pytest_bazel

from devinfra.claude.hook_daemon.shim_install import SHIM_DIR_ENV, resolve_real_binary


def test_resolve_real_binary_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """When no binary is on PATH, raises FileNotFoundError."""
    monkeypatch.setenv("PATH", "/nonexistent")
    monkeypatch.delenv(SHIM_DIR_ENV, raising=False)

    with pytest.raises(FileNotFoundError, match="bazelisk"):
        resolve_real_binary("bazelisk")


if __name__ == "__main__":
    pytest_bazel.main()
