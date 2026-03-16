"""Unit tests for bazel_wrapper."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_bazel

from devinfra.claude.bazel_wrapper import _resolve_real_binary
from devinfra.claude.env_file import ENV_BAZELISK_PATH


def test_resolve_real_binary_uses_bazelisk_path(tmp_path: Path) -> None:
    """When BAZELISK_PATH is set, _resolve_real_binary returns it."""
    fake_bazelisk = tmp_path / "bazelisk"
    fake_bazelisk.write_text("#!/bin/sh")
    fake_bazelisk.chmod(0o755)

    with patch.dict(os.environ, {ENV_BAZELISK_PATH: str(fake_bazelisk)}):
        assert _resolve_real_binary() == str(fake_bazelisk)


def test_resolve_real_binary_missing_bazelisk_raises(tmp_path: Path) -> None:
    """When BAZELISK_PATH points to a non-existent file, FileNotFoundError is raised."""
    with (
        patch.dict(os.environ, {ENV_BAZELISK_PATH: str(tmp_path / "nonexistent")}),
        pytest.raises(FileNotFoundError, match="does not exist"),
    ):
        _resolve_real_binary()


if __name__ == "__main__":
    pytest_bazel.main()
