"""SOPS YAML decryption via the sops CLI.

sops natively reads SOPS_AGE_KEY from the environment for age-based decryption.
No custom env var handling needed — callers set SOPS_AGE_KEY and sops picks it up.
"""

import logging
import subprocess
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


def decrypt_sops_yaml(path: Path) -> dict[str, str]:
    """Decrypt a SOPS-encrypted YAML file, returning plaintext key-value pairs."""
    result = subprocess.run(["sops", "decrypt", path], capture_output=True, text=True, check=True)
    raw = yaml.safe_load(result.stdout)
    if not isinstance(raw, dict):
        raise ValueError(f"Expected YAML dict, got {type(raw).__name__}")
    return {k: str(v) for k, v in raw.items()}
