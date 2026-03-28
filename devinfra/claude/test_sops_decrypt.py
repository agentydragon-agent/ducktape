"""Tests for SOPS YAML decryption via pyrage."""

import base64
import hashlib
import hmac
import os
from pathlib import Path

import pytest
import pytest_bazel
import yaml
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pyrage import encrypt, x25519

from devinfra.claude.sops_decrypt import _parse_enc_value, decrypt_sops_yaml, load_age_identities

# Test-only age keypair (deterministic, not used for real secrets)
_TEST_IDENTITY = x25519.Identity.generate()
_TEST_RECIPIENT = _TEST_IDENTITY.to_public()


def _sops_encrypt_value(value: str, data_key: bytes, key_path: str) -> str:
    """Encrypt a value in SOPS ENC[AES256_GCM,...] format."""
    aesgcm = AESGCM(data_key)
    iv = b"\x00" * 12  # deterministic IV for tests
    aad = key_path.encode()
    ct = aesgcm.encrypt(iv, value.encode(), aad)
    # ct = ciphertext || tag (last 16 bytes)
    ciphertext, tag = ct[:-16], ct[-16:]
    data_b64 = base64.b64encode(ciphertext).decode()
    iv_b64 = base64.b64encode(iv).decode()
    tag_b64 = base64.b64encode(tag).decode()
    return f"ENC[AES256_GCM,data:{data_b64},iv:{iv_b64},tag:{tag_b64},type:str]"


def _build_sops_yaml(plaintext_values: dict[str, str]) -> str:
    """Build a complete SOPS-encrypted YAML document with valid MAC."""
    data_key = os.urandom(32)

    # Encrypt each value
    encrypted: dict[str, str] = {}
    for key, value in plaintext_values.items():
        encrypted[key] = _sops_encrypt_value(value, data_key, key)

    # Compute MAC: HMAC-SHA256 of values concatenated in sorted key order
    h = hmac.new(data_key, digestmod=hashlib.sha256)
    for key in sorted(plaintext_values.keys()):
        h.update(plaintext_values[key].encode())
    mac_hex = h.hexdigest()

    # Encrypt the MAC itself
    aesgcm = AESGCM(data_key)
    mac_iv = b"\x01" * 12
    mac_ct = aesgcm.encrypt(mac_iv, mac_hex.encode(), b"")
    mac_ciphertext, mac_tag = mac_ct[:-16], mac_ct[-16:]
    mac_enc = (
        f"ENC[AES256_GCM,"
        f"data:{base64.b64encode(mac_ciphertext).decode()},"
        f"iv:{base64.b64encode(mac_iv).decode()},"
        f"tag:{base64.b64encode(mac_tag).decode()},"
        f"type:str]"
    )

    # Encrypt data key for the test recipient using age
    age_encrypted_key_binary = encrypt(data_key, [_TEST_RECIPIENT])

    sops_metadata = {
        "age": [{"recipient": str(_TEST_RECIPIENT), "enc": age_encrypted_key_binary}],
        "lastmodified": "2026-03-28T00:00:00Z",
        "mac": mac_enc,
        "version": "3.9.0",
    }

    doc = {**encrypted, "sops": sops_metadata}
    return yaml.dump(doc, default_flow_style=False)


@pytest.fixture
def sops_file(tmp_path: Path) -> Path:
    """Create a test SOPS-encrypted YAML file."""
    content = _build_sops_yaml({"api_key": "test-secret-value", "another_key": "another-secret"})
    path = tmp_path / "test_secrets.yaml"
    path.write_text(content)
    return path


def test_parse_enc_value():
    enc = "ENC[AES256_GCM,data:dGVzdA==,iv:AAAAAAAAAAAAAAAA,tag:AAAAAAAAAAAAAAAAAAAAAA==,type:str]"
    ct_tag, iv, value_type = _parse_enc_value(enc)
    assert iv == b"\x00" * 12
    assert value_type == b"str"
    assert len(ct_tag) > 0


def test_parse_enc_value_invalid():
    with pytest.raises(ValueError, match="Not a valid SOPS"):
        _parse_enc_value("not-encrypted")


def test_decrypt_sops_yaml(sops_file: Path):
    result = decrypt_sops_yaml(sops_file, [_TEST_IDENTITY])
    assert result == {"api_key": "test-secret-value", "another_key": "another-secret"}


def test_decrypt_sops_yaml_no_sops_metadata(tmp_path: Path):
    path = tmp_path / "plain.yaml"
    path.write_text("key: value\n")
    with pytest.raises(ValueError, match="No 'sops' metadata"):
        decrypt_sops_yaml(path, [_TEST_IDENTITY])


def test_decrypt_sops_yaml_wrong_identity(sops_file: Path):
    wrong_identity = x25519.Identity.generate()
    with pytest.raises(ValueError, match="Could not decrypt SOPS data key"):
        decrypt_sops_yaml(sops_file, [wrong_identity])


def test_load_age_identities():
    key_str = str(_TEST_IDENTITY)
    identities = load_age_identities(key_str)
    assert len(identities) == 1


def test_load_age_identities_with_comments():
    key_str = f"# created: 2026-03-28\n# public key: ...\n{_TEST_IDENTITY}\n"
    identities = load_age_identities(key_str)
    assert len(identities) == 1


def test_load_age_identities_empty():
    with pytest.raises(ValueError, match="No AGE-SECRET-KEY"):
        load_age_identities("# just a comment\n")


def test_roundtrip_with_env_var_key(sops_file: Path):
    """End-to-end: load identity from string (as env var would provide), decrypt."""
    identities = load_age_identities(str(_TEST_IDENTITY))
    result = decrypt_sops_yaml(sops_file, identities)
    assert result["api_key"] == "test-secret-value"


if __name__ == "__main__":
    pytest_bazel.main()
