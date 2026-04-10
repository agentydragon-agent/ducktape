"""Tests for SOPS YAML decryption via sops CLI."""

import os
import subprocess
from pathlib import Path

import pytest
import pytest_bazel

from devinfra.claude.hook_daemon.session_start.sops_decrypt import decrypt_sops_yaml
from util.bazel.runfiles import get_required_path

_TESTDATA_YAML = "_main/devinfra/claude/testdata/sops_test_secrets.yaml"
_TESTDATA_AGE_KEY = "_main/devinfra/claude/testdata/sops_test_age_key.txt"
_EXPECTED = {"api_key": "test-secret-value", "another_key": "another-secret"}


@pytest.fixture(autouse=True)
def _sops_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure the multitool sops binary is on PATH."""
    if sops_rlocation := os.environ.get("SOPS_BIN"):
        sops_path = get_required_path(sops_rlocation)
        monkeypatch.setenv("PATH", f"{sops_path.parent}:{os.environ.get('PATH', '')}")


@pytest.fixture
def age_key() -> str:
    return get_required_path(_TESTDATA_AGE_KEY).read_text().strip()


@pytest.fixture
def sops_file() -> Path:
    return get_required_path(_TESTDATA_YAML)


def test_decrypt_sops_yaml(sops_file: Path, age_key: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SOPS_AGE_KEY", age_key)
    result = decrypt_sops_yaml(sops_file)
    assert result == _EXPECTED


def test_decrypt_sops_yaml_wrong_key(sops_file: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SOPS_AGE_KEY", "AGE-SECRET-KEY-1QQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQ")
    with pytest.raises(subprocess.CalledProcessError):
        decrypt_sops_yaml(sops_file)


if __name__ == "__main__":
    pytest_bazel.main()
