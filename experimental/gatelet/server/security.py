"""Password hashing helpers."""

import binascii
import hashlib
import os


def hash_password(password: str, salt: str | None = None) -> str:
    """Return PBKDF2-HMAC-SHA256 hash of the password with a hex salt."""
    salt_bytes = os.urandom(16) if salt is None else bytes.fromhex(salt)
    pwd_hash = hashlib.pbkdf2_hmac("sha256", password.encode(), salt_bytes, 100000)
    return f"{salt_bytes.hex()}${binascii.hexlify(pwd_hash).decode()}"


def verify_password(password: str, hashed: str) -> bool:
    """Verify password against stored hash."""
    try:
        salt_hex, hash_hex = hashed.split("$")
    except ValueError:
        return False
    salt_bytes = bytes.fromhex(salt_hex)
    expected = hashlib.pbkdf2_hmac("sha256", password.encode(), salt_bytes, 100000)
    return binascii.hexlify(expected).decode() == hash_hex
