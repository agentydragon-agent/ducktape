"""Tests for CLI-mode environment file generation.

Verifies that write_env_file with CLI-mode EnvVars writes the wrapper PATH,
SESSION_BAZELRC, and direnv eval for .envrc propagation into subsequent Bash
tool calls.
"""

from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_bazel

from devinfra.claude.env_file import EnvVars, write_env_file


def _cli_env_vars(wrapper_dir: Path, bazelrc: Path, *, with_direnv: bool = False) -> EnvVars:
    return EnvVars(bazel_wrapper_dir=wrapper_dir, session_bazelrc=bazelrc, with_direnv=with_direnv)


@pytest.fixture
def env_file(tmp_path: Path) -> Path:
    return tmp_path / "env.sh"


@pytest.fixture
def wrapper_dir(tmp_path: Path) -> Path:
    return tmp_path / "bin"


@pytest.fixture
def bazelrc(tmp_path: Path) -> Path:
    path = tmp_path / "bazelrc"
    path.write_text("# test")
    return path


def test_contains_wrapper_path(env_file: Path, wrapper_dir: Path, bazelrc: Path) -> None:
    """Env file puts the wrapper directory on PATH."""
    write_env_file(env_file, _cli_env_vars(wrapper_dir, bazelrc))

    content = env_file.read_text()
    assert str(wrapper_dir) in content
    assert "PATH=" in content


def test_exports_session_bazelrc(env_file: Path, wrapper_dir: Path, bazelrc: Path) -> None:
    """Env file exports SESSION_BAZELRC pointing to the rendered bazelrc."""
    write_env_file(env_file, _cli_env_vars(wrapper_dir, bazelrc))

    content = env_file.read_text()
    assert "SESSION_BAZELRC=" in content
    assert str(bazelrc) in content


def test_includes_direnv_eval(env_file: Path, wrapper_dir: Path, bazelrc: Path) -> None:
    """When direnv is available, env file includes dynamic eval."""
    with patch("devinfra.claude.env_file.shutil.which", return_value="/usr/bin/direnv"):
        write_env_file(env_file, _cli_env_vars(wrapper_dir, bazelrc, with_direnv=True))

    content = env_file.read_text()
    assert 'eval "$(direnv export bash 2>/dev/null)"' in content


def test_exports_ansible_local_temp(env_file: Path, wrapper_dir: Path, bazelrc: Path) -> None:
    """Env file exports ANSIBLE_LOCAL_TEMP so pre-commit works in read-only sandboxes."""
    write_env_file(env_file, _cli_env_vars(wrapper_dir, bazelrc))

    content = env_file.read_text()
    assert "ANSIBLE_LOCAL_TEMP=" in content


def test_no_direnv_when_missing(env_file: Path, wrapper_dir: Path, bazelrc: Path) -> None:
    """When direnv is not installed, env file omits the eval."""
    with patch("devinfra.claude.env_file.shutil.which", return_value=None):
        write_env_file(env_file, _cli_env_vars(wrapper_dir, bazelrc, with_direnv=True))

    content = env_file.read_text()
    assert "direnv export" not in content


if __name__ == "__main__":
    pytest_bazel.main()
