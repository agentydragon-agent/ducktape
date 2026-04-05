"""Tests for SOPS YAML decryption via pyrage.

Uses testdata files encrypted by the real sops CLI (not synthetic encryption),
so the tests validate against the actual SOPS format.
"""

from pathlib import Path

import pytest
import pytest_bazel
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key as generate_rsa_key
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
from pyrage import x25519

from devinfra.claude.sops_decrypt import (
    _parse_enc_value,
    _ssh_ed25519_to_age_identity,
    decrypt_sops_yaml,
    discover_age_identities,
    load_age_identities,
)
from util.bazel.runfiles import get_required_path

# Committed testdata encrypted by `sops --encrypt --age <recipient>`.
_TESTDATA_YAML = "_main/devinfra/claude/testdata/sops_test_secrets.yaml"
_TESTDATA_AGE_KEY = "_main/devinfra/claude/testdata/sops_test_age_key.txt"
# Passphrase-protected ed25519 key (password: "testpass"), generated via ssh-keygen.
_TESTDATA_ENCRYPTED_SSH_KEY = "_main/devinfra/claude/testdata/ssh_encrypted_ed25519"

_EXPECTED = {"api_key": "test-secret-value", "another_key": "another-secret"}


@pytest.fixture
def sops_file() -> Path:
    return get_required_path(_TESTDATA_YAML)


@pytest.fixture
def test_identities() -> list:
    key_text = get_required_path(_TESTDATA_AGE_KEY).read_text()
    return load_age_identities(key_text)


def test_parse_enc_value():
    enc = "ENC[AES256_GCM,data:dGVzdA==,iv:AAAAAAAAAAAAAAAA,tag:AAAAAAAAAAAAAAAAAAAAAA==,type:str]"
    ct_tag, iv, value_type = _parse_enc_value(enc)
    assert iv == b"\x00" * 12
    assert value_type == b"str"
    assert len(ct_tag) > 0


def test_parse_enc_value_invalid():
    with pytest.raises(ValueError, match="Not a valid SOPS"):
        _parse_enc_value("not-encrypted")


def test_decrypt_sops_yaml(sops_file: Path, test_identities: list):
    """Decrypt a file encrypted by the real sops CLI."""
    result = decrypt_sops_yaml(sops_file, test_identities)
    assert result == _EXPECTED


def test_decrypt_sops_yaml_no_sops_metadata(tmp_path: Path, test_identities: list):
    path = tmp_path / "plain.yaml"
    path.write_text("key: value\n")
    with pytest.raises(ValueError, match="No 'sops' metadata"):
        decrypt_sops_yaml(path, test_identities)


def test_decrypt_sops_yaml_wrong_identity(sops_file: Path):
    wrong_identity = x25519.Identity.generate()
    with pytest.raises(ValueError, match="Could not decrypt SOPS data key"):
        decrypt_sops_yaml(sops_file, [wrong_identity])


def test_load_age_identities():
    key_text = get_required_path(_TESTDATA_AGE_KEY).read_text()
    identities = load_age_identities(key_text)
    assert len(identities) == 1


def test_load_age_identities_with_comments():
    key_text = "# created: 2026-03-28\n# public key: ...\nAGE-SECRET-KEY-1VL0XPAP3L02ZMAKXWDF0WQLGYCTYUQF77N4FDLHSCZJVMMW7TH4QS2APFM\n"
    identities = load_age_identities(key_text)
    assert len(identities) == 1


def test_load_age_identities_empty():
    with pytest.raises(ValueError, match="No AGE-SECRET-KEY"):
        load_age_identities("# just a comment\n")


def test_roundtrip_with_env_var_key(sops_file: Path):
    """End-to-end: load identity from key file text, decrypt real sops file."""
    key_text = get_required_path(_TESTDATA_AGE_KEY).read_text()
    identities = load_age_identities(key_text)
    result = decrypt_sops_yaml(sops_file, identities)
    assert result["api_key"] == "test-secret-value"


def test_discover_age_identities_from_env_var(monkeypatch: pytest.MonkeyPatch):
    """DUCKTAPE_CLAUDE_HOOKS_AGE_KEY takes priority."""
    key_text = get_required_path(_TESTDATA_AGE_KEY).read_text()
    monkeypatch.setenv("DUCKTAPE_CLAUDE_HOOKS_AGE_KEY", key_text)
    identities = discover_age_identities()
    assert identities is not None
    assert len(identities) == 1


def test_discover_age_identities_from_sops_age_key(monkeypatch: pytest.MonkeyPatch):
    """SOPS_AGE_KEY env var works as inline key."""
    key_text = get_required_path(_TESTDATA_AGE_KEY).read_text()
    monkeypatch.delenv("DUCKTAPE_CLAUDE_HOOKS_AGE_KEY", raising=False)
    monkeypatch.setenv("SOPS_AGE_KEY", key_text)
    identities = discover_age_identities()
    assert identities is not None
    assert len(identities) == 1


def test_discover_age_identities_from_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Falls back to key file when no inline env vars set."""
    key_file = tmp_path / "keys.txt"
    key_file.write_text(get_required_path(_TESTDATA_AGE_KEY).read_text())
    monkeypatch.delenv("DUCKTAPE_CLAUDE_HOOKS_AGE_KEY", raising=False)
    monkeypatch.delenv("SOPS_AGE_KEY", raising=False)
    monkeypatch.setenv("SOPS_AGE_KEY_FILE", str(key_file))
    identities = discover_age_identities()
    assert identities is not None
    assert len(identities) == 1


@pytest.fixture
def no_age_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Clear all age key sources, redirect HOME to tmp_path."""
    monkeypatch.delenv("DUCKTAPE_CLAUDE_HOOKS_AGE_KEY", raising=False)
    monkeypatch.delenv("SOPS_AGE_KEY", raising=False)
    monkeypatch.setenv("SOPS_AGE_KEY_FILE", str(tmp_path / "nonexistent.txt"))
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def test_discover_age_identities_no_file(no_age_sources: Path):
    """Returns empty list when no key file and no SSH key exist."""
    assert discover_age_identities() == []


def test_discover_age_identities_empty_file(no_age_sources: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Returns empty list when key file has no valid keys and no SSH key exists."""
    key_file = tmp_path / "keys.txt"
    key_file.write_text("# just a comment\n")
    monkeypatch.setenv("SOPS_AGE_KEY_FILE", str(key_file))
    assert discover_age_identities() == []


# === SSH ed25519 -> age identity conversion ===


def _write_ed25519_key(path: Path) -> Ed25519PrivateKey:
    """Generate and write an unencrypted ed25519 SSH key to the given path."""
    key = Ed25519PrivateKey.generate()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(key.private_bytes(Encoding.PEM, PrivateFormat.OpenSSH, NoEncryption()))
    return key


def test_ssh_ed25519_to_age_identity_valid(tmp_path: Path):
    key_path = tmp_path / "id_ed25519"
    _write_ed25519_key(key_path)
    identity = _ssh_ed25519_to_age_identity(key_path)
    assert identity is not None
    assert str(identity.to_public()).startswith("age1")


def test_ssh_ed25519_to_age_identity_missing_file(tmp_path: Path):
    assert _ssh_ed25519_to_age_identity(tmp_path / "nonexistent") is None


def test_ssh_ed25519_to_age_identity_passphrase_protected():
    """Passphrase-protected keys are skipped (returns None)."""
    key_path = get_required_path(_TESTDATA_ENCRYPTED_SSH_KEY)
    assert _ssh_ed25519_to_age_identity(key_path) is None


def test_ssh_ed25519_to_age_identity_wrong_key_type(tmp_path: Path):
    key_path = tmp_path / "id_rsa"
    rsa_key = generate_rsa_key(public_exponent=65537, key_size=2048)
    key_path.write_bytes(rsa_key.private_bytes(Encoding.PEM, PrivateFormat.OpenSSH, NoEncryption()))
    assert _ssh_ed25519_to_age_identity(key_path) is None


def test_discover_age_identities_ssh_fallback(no_age_sources: Path):
    """Falls back to SSH key when no age env vars or key files exist."""
    ssh_dir = no_age_sources / ".ssh"
    _write_ed25519_key(ssh_dir / "id_ed25519")
    identities = discover_age_identities()
    assert len(identities) == 1


if __name__ == "__main__":
    pytest_bazel.main()
