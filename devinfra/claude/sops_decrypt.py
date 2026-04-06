"""SOPS YAML decryption using pyrage (age encryption).

Parses SOPS-encrypted YAML files and decrypts values in-process using age
identities (native age keys or SSH ed25519 keys). No subprocess or ``sops``
binary required.

SOPS format: each encrypted value is
``ENC[AES256_GCM,data:<base64>,iv:<base64>,tag:<base64>,type:str]``.
The per-file data key is age-encrypted per recipient in the ``sops.age[]``
metadata block.
"""

import base64
import hashlib
import hmac
import logging
import os
import re
from pathlib import Path

import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, ssh as ssh_serialization
from pyrage import decrypt, x25519

from util.bech32 import encode as bech32_encode

logger = logging.getLogger(__name__)

_ENC_PATTERN = re.compile(
    r"^ENC\[AES256_GCM,"
    r"data:(?P<data>[A-Za-z0-9+/=]+),"
    r"iv:(?P<iv>[A-Za-z0-9+/=]+),"
    r"tag:(?P<tag>[A-Za-z0-9+/=]+),"
    r"type:(?P<type>\w+)\]$"
)


def _parse_enc_value(value: str) -> tuple[bytes, bytes, bytes]:
    """Parse an ENC[AES256_GCM,...] string into (ciphertext+tag, iv, original_type)."""
    m = _ENC_PATTERN.match(value)
    if not m:
        raise ValueError(f"Not a valid SOPS encrypted value: {value!r}")
    data = base64.b64decode(m.group("data"))
    iv = base64.b64decode(m.group("iv"))
    tag = base64.b64decode(m.group("tag"))
    # AES-GCM: ciphertext || tag (cryptography library expects this layout)
    return data + tag, iv, m.group("type").encode()


def _decrypt_data_key(sops_metadata: dict, identities: list) -> bytes:
    """Decrypt the SOPS data key using age identities.

    The data key is stored as an age-encrypted blob in the sops.age[] array.
    Each entry is encrypted for a different recipient; we try all until one
    succeeds.
    """
    age_entries = sops_metadata.get("age", [])
    if not age_entries:
        raise ValueError("No age recipients in SOPS metadata")

    errors: list[str] = []
    for entry in age_entries:
        enc_blob = entry.get("enc", b"")
        if not enc_blob:
            continue
        enc_bytes = enc_blob if isinstance(enc_blob, bytes) else enc_blob.encode()
        try:
            result: bytes = decrypt(enc_bytes, identities)
            return result
        except Exception as e:
            errors.append(f"recipient {entry.get('recipient', '?')}: {e}")

    raise ValueError(f"Could not decrypt SOPS data key with any identity: {'; '.join(errors)}")


def _decrypt_value(ciphertext_and_tag: bytes, iv: bytes, data_key: bytes, aad: bytes) -> str:
    """Decrypt a single SOPS value using AES-256-GCM."""
    aesgcm = AESGCM(data_key)
    plaintext = aesgcm.decrypt(iv, ciphertext_and_tag, aad)
    return plaintext.decode()


def _compute_aad(key_path: str) -> bytes:
    """Compute the AAD for a SOPS value.

    SOPS uses the key path with a trailing colon as AAD for top-level keys
    (e.g. ``buildbuddy_api_key`` -> ``buildbuddy_api_key:``).
    """
    return f"{key_path}:".encode()


def _verify_mac(sops_metadata: dict, decrypted_values: dict[str, str], data_key: bytes) -> None:
    """Verify the SOPS MAC to ensure data integrity.

    SOPS computes SHA-512 over all decrypted values in document order, then
    encrypts the hex digest with AES-GCM using ``lastmodified`` as AAD.
    """
    mac_enc = sops_metadata.get("mac")
    if not mac_enc:
        logger.warning("No MAC in SOPS metadata, skipping integrity check")
        return

    mac_ct_tag, mac_iv, _ = _parse_enc_value(mac_enc)
    lastmodified = sops_metadata.get("lastmodified", "")
    aesgcm = AESGCM(data_key)
    expected_mac_bytes = aesgcm.decrypt(mac_iv, mac_ct_tag, lastmodified.encode())
    expected_mac = expected_mac_bytes.decode()

    # Values are hashed in YAML document order (dict preserves insertion order).
    h = hashlib.sha512()
    for value in decrypted_values.values():
        h.update(value.encode())
    computed_mac = h.hexdigest().upper()

    if not hmac.compare_digest(computed_mac, expected_mac):
        raise ValueError("SOPS MAC verification failed — file may be tampered")


def decrypt_sops_yaml(path: Path, identities: list) -> dict[str, str]:
    """Decrypt a SOPS-encrypted YAML file, returning plaintext key-value pairs.

    Only decrypts top-level string values (the common case for secret files).
    The ``sops`` metadata key is excluded from the result.
    """
    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"Expected YAML dict, got {type(raw).__name__}")

    sops_metadata = raw.get("sops")
    if not sops_metadata:
        raise ValueError(f"No 'sops' metadata in {path} — is this a SOPS-encrypted file?")

    data_key = _decrypt_data_key(sops_metadata, identities)

    result: dict[str, str] = {}
    for key, value in raw.items():
        if key == "sops":
            continue
        if not isinstance(value, str) or not value.startswith("ENC["):
            result[key] = str(value)
            continue
        ct_tag, iv, _ = _parse_enc_value(value)
        aad = _compute_aad(key)
        result[key] = _decrypt_value(ct_tag, iv, data_key, aad)

    _verify_mac(sops_metadata, result, data_key)
    return result


# === SSH ed25519 -> age identity conversion ===


def _ssh_ed25519_to_age_identity(ssh_key_path: Path) -> x25519.Identity | None:
    """Convert an SSH ed25519 private key to an age x25519 identity.

    Uses the same derivation as ssh-to-age: ed25519 seed -> SHA-512 -> X25519
    clamping -> bech32 encode as AGE-SECRET-KEY-...
    """
    try:
        key_data = ssh_key_path.read_bytes()
    except (FileNotFoundError, PermissionError):
        logger.debug("No SSH key at %s", ssh_key_path)
        return None
    try:
        private_key = ssh_serialization.load_ssh_private_key(key_data, password=None)
    except (ValueError, TypeError):
        logger.exception(
            "SSH key at %s is passphrase-protected or invalid, cannot convert to age identity", ssh_key_path
        )
        return None
    if not isinstance(private_key, Ed25519PrivateKey):
        logger.warning(
            "SSH key at %s is %s, not ed25519 — cannot convert to age identity",
            ssh_key_path,
            type(private_key).__name__,
        )
        return None
    seed = private_key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    # Ed25519 seed -> X25519 private key (SHA-512 + clamping)
    h = bytearray(hashlib.sha512(seed).digest()[:32])
    h[0] &= 248
    h[31] &= 127
    h[31] |= 64
    age_key = bech32_encode("age-secret-key-", bytes(h)).upper()
    identity = x25519.Identity.from_str(age_key)
    logger.debug("Converted SSH key %s to age identity", ssh_key_path)
    return identity


# === Age identity discovery ===


def _parse_age_keys(text: str) -> list:
    """Parse age identity keys from text (age key file format, one key per line)."""
    identities: list = []
    for raw_line in text.strip().splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("AGE-SECRET-KEY-"):
            identities.append(x25519.Identity.from_str(stripped))
    return identities


def load_age_identities(age_key: str) -> list:
    """Load age identities from a key string (age identity file format).

    The string may contain one or more AGE-SECRET-KEY-... lines, optionally
    with comments (lines starting with #). This is the same format as an
    age identity file, suitable for passing via environment variable.
    """
    identities = _parse_age_keys(age_key)
    if not identities:
        raise ValueError("No AGE-SECRET-KEY-... lines found in age_key")
    return identities


_DEFAULT_AGE_KEY_FILE = Path.home() / ".config" / "sops" / "age" / "keys.txt"


def discover_age_identities() -> list:
    """Discover age identities from all available sources.

    Checks each source and collects all identities found:
    1. ``DUCKTAPE_CLAUDE_HOOKS_AGE_KEY`` env var (inline key, web mode)
    2. ``SOPS_AGE_KEY`` env var (inline key, sops convention)
    3. ``SOPS_AGE_KEY_FILE`` env var -> read that file
    4. ``~/.config/sops/age/keys.txt`` (standard sops default)
    5. ``~/.ssh/id_ed25519`` -> convert to age identity (CLI fallback)
    """
    identities: list = []
    for env_var in ("DUCKTAPE_CLAUDE_HOOKS_AGE_KEY", "SOPS_AGE_KEY"):
        if inline_key := os.environ.get(env_var):
            logger.debug("Loading age identities from %s", env_var)
            identities.extend(load_age_identities(inline_key))
    key_file = Path(os.environ["SOPS_AGE_KEY_FILE"]) if "SOPS_AGE_KEY_FILE" in os.environ else _DEFAULT_AGE_KEY_FILE
    try:
        key_text = key_file.read_text()
    except FileNotFoundError:
        logger.debug("No age key file at %s", key_file)
    else:
        file_identities = _parse_age_keys(key_text)
        if not file_identities:
            logger.warning("Age key file %s exists but contains no valid keys", key_file)
        else:
            logger.debug("Loaded %d age identity(ies) from %s", len(file_identities), key_file)
            identities.extend(file_identities)
    # Derive age identity from SSH ed25519 key (CLI mode fallback)
    ssh_key = Path.home() / ".ssh" / "id_ed25519"
    if identity := _ssh_ed25519_to_age_identity(ssh_key):
        logger.debug("Loaded age identity from SSH key at %s", ssh_key)
        identities.append(identity)
    if not identities:
        logger.warning("No age identities found from any source (env vars, key files, SSH key)")
    return identities
