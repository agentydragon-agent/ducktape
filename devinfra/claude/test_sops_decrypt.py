"""Tests for SOPS YAML decryption via sops CLI."""

import shutil
import subprocess
from pathlib import Path

import pytest
import pytest_bazel

from devinfra.claude.sops_decrypt import decrypt_sops_yaml, discover_age_key
from util.bazel.runfiles import get_required_path

# TODO: add sops to multitool or Bazel-managed tools so tests run on RBE.
pytestmark = pytest.mark.skipif(shutil.which("sops") is None, reason="sops not on PATH")

_TESTDATA_YAML = "_main/devinfra/claude/testdata/sops_test_secrets.yaml"
_TESTDATA_AGE_KEY = "_main/devinfra/claude/testdata/sops_test_age_key.txt"

_EXPECTED = {"api_key": "test-secret-value", "another_key": "another-secret"}


@pytest.fixture
def age_key() -> str:
    return get_required_path(_TESTDATA_AGE_KEY).read_text().strip()


@pytest.fixture
def sops_file() -> Path:
    return get_required_path(_TESTDATA_YAML)


def test_decrypt_sops_yaml(sops_file: Path, age_key: str):
    result = decrypt_sops_yaml(sops_file, age_key=age_key)
    assert result == _EXPECTED


def test_decrypt_sops_yaml_wrong_key(sops_file: Path):
    with pytest.raises(subprocess.CalledProcessError):
        decrypt_sops_yaml(
            sops_file, age_key="AGE-SECRET-KEY-1QQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQ"
        )


def test_discover_age_key_from_ducktape_env(monkeypatch: pytest.MonkeyPatch, age_key: str):
    monkeypatch.setenv("DUCKTAPE_CLAUDE_HOOKS_AGE_KEY", age_key)
    monkeypatch.delenv("SOPS_AGE_KEY", raising=False)
    assert discover_age_key() == age_key


def test_discover_age_key_from_sops_env(monkeypatch: pytest.MonkeyPatch, age_key: str):
    monkeypatch.delenv("DUCKTAPE_CLAUDE_HOOKS_AGE_KEY", raising=False)
    monkeypatch.setenv("SOPS_AGE_KEY", age_key)
    assert discover_age_key() == age_key


def test_discover_age_key_none(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DUCKTAPE_CLAUDE_HOOKS_AGE_KEY", raising=False)
    monkeypatch.delenv("SOPS_AGE_KEY", raising=False)
    assert discover_age_key() is None


if __name__ == "__main__":
    pytest_bazel.main()
