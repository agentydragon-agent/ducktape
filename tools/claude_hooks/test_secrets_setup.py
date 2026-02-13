"""Unit tests for secrets_setup module."""

from __future__ import annotations

import json
from pathlib import Path

import pyrage
import pytest
import pytest_bazel

from tools.claude_hooks.secrets_setup import SecretsSetup, setup_secrets


def _encrypt_json(data: dict[str, str], recipient: pyrage.x25519.Recipient) -> bytes:
    """Encrypt a JSON dict to an age recipient."""
    result: bytes = pyrage.encrypt(json.dumps(data).encode(), [recipient])
    return result


@pytest.fixture
def age_keypair() -> tuple[pyrage.x25519.Identity, pyrage.x25519.Recipient]:
    """Generate a fresh age keypair for testing."""
    identity = pyrage.x25519.Identity.generate()
    recipient = identity.to_public()
    return identity, recipient


@pytest.fixture
def secrets_dir(tmp_path: Path) -> Path:
    """Create a secrets directory."""
    d = tmp_path / "secrets"
    d.mkdir()
    return d


def test_no_age_key_returns_none(secrets_dir: Path) -> None:
    result = setup_secrets(age_key=None, secrets_dir=secrets_dir)
    assert result is None


def test_missing_dir_returns_none() -> None:
    result = setup_secrets(age_key="AGE-SECRET-KEY-1FAKE", secrets_dir=Path("/nonexistent"))
    assert result is None


def test_successful_decryption(
    secrets_dir: Path, age_keypair: tuple[pyrage.x25519.Identity, pyrage.x25519.Recipient]
) -> None:
    identity, recipient = age_keypair
    (secrets_dir / "test.age").write_bytes(_encrypt_json({"FOO": "bar"}, recipient))

    result = setup_secrets(age_key=str(identity), secrets_dir=secrets_dir)

    assert result is not None
    assert result.env_vars == {"FOO": "bar"}
    assert result.skipped_files == []


def test_all_files_skipped_on_wrong_key(
    secrets_dir: Path, age_keypair: tuple[pyrage.x25519.Identity, pyrage.x25519.Recipient]
) -> None:
    """When age_key doesn't match any file, all files are skipped."""
    _, recipient = age_keypair
    (secrets_dir / "a.age").write_bytes(_encrypt_json({"A": "1"}, recipient))
    (secrets_dir / "b.age").write_bytes(_encrypt_json({"B": "2"}, recipient))

    # Use a different key that won't match
    wrong_identity = pyrage.x25519.Identity.generate()

    result = setup_secrets(age_key=str(wrong_identity), secrets_dir=secrets_dir)

    assert result is not None
    assert result.env_vars == {}
    assert sorted(result.skipped_files) == ["a.age", "b.age"]


def test_partial_decryption_tracks_skipped(secrets_dir: Path) -> None:
    """When some files match and others don't, skipped files are tracked."""
    id1 = pyrage.x25519.Identity.generate()
    id2 = pyrage.x25519.Identity.generate()

    # Encrypt one file to id1, another to id2
    (secrets_dir / "matches.age").write_bytes(_encrypt_json({"MATCH": "yes"}, id1.to_public()))
    (secrets_dir / "nomatch.age").write_bytes(_encrypt_json({"SKIP": "no"}, id2.to_public()))

    result = setup_secrets(age_key=str(id1), secrets_dir=secrets_dir)

    assert result is not None
    assert result.env_vars == {"MATCH": "yes"}
    assert result.skipped_files == ["nomatch.age"]


def test_duplicate_keys_across_files_raises(
    secrets_dir: Path, age_keypair: tuple[pyrage.x25519.Identity, pyrage.x25519.Recipient]
) -> None:
    identity, recipient = age_keypair
    (secrets_dir / "a.age").write_bytes(_encrypt_json({"DUP": "1"}, recipient))
    (secrets_dir / "b.age").write_bytes(_encrypt_json({"DUP": "2"}, recipient))

    with pytest.raises(ValueError, match="Duplicate env var keys"):
        setup_secrets(age_key=str(identity), secrets_dir=secrets_dir)


def test_empty_dir_returns_empty(
    secrets_dir: Path, age_keypair: tuple[pyrage.x25519.Identity, pyrage.x25519.Recipient]
) -> None:
    identity, _ = age_keypair
    result = setup_secrets(age_key=str(identity), secrets_dir=secrets_dir)

    assert result is not None
    assert result.env_vars == {}
    assert result.skipped_files == []


def test_env_exports_format(
    secrets_dir: Path, age_keypair: tuple[pyrage.x25519.Identity, pyrage.x25519.Recipient]
) -> None:
    identity, recipient = age_keypair
    (secrets_dir / "test.age").write_bytes(_encrypt_json({"TOKEN": "abc 123", "KEY": "def"}, recipient))

    result = setup_secrets(age_key=str(identity), secrets_dir=secrets_dir)

    assert result is not None
    # env_exports should produce sorted shell export lines
    assert "export KEY=" in result.env_exports
    assert "export TOKEN=" in result.env_exports


def test_secrets_setup_skipped_files_default() -> None:
    """Verify SecretsSetup defaults."""
    setup = SecretsSetup()
    assert setup.env_vars == {}
    assert setup.skipped_files == []
    assert setup.env_exports == ""


if __name__ == "__main__":
    pytest_bazel.main()
