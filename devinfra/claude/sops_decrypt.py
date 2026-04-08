"""SOPS YAML decryption via the sops CLI."""

import logging
import os
import subprocess
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


def decrypt_sops_yaml(path: Path, age_key: str | None = None) -> dict[str, str]:
    """Decrypt a SOPS-encrypted YAML file, returning plaintext key-value pairs."""
    env = {**os.environ}
    if age_key:
        env["SOPS_AGE_KEY"] = age_key
    result = subprocess.run(["sops", "decrypt", str(path)], capture_output=True, text=True, check=True, env=env)
    raw = yaml.safe_load(result.stdout)
    if not isinstance(raw, dict):
        raise ValueError(f"Expected YAML dict, got {type(raw).__name__}")
    return {k: str(v) for k, v in raw.items()}


def discover_age_key() -> str | None:
    """Find age key from DUCKTAPE_CLAUDE_HOOKS_AGE_KEY or SOPS_AGE_KEY."""
    for var in ("DUCKTAPE_CLAUDE_HOOKS_AGE_KEY", "SOPS_AGE_KEY"):
        if val := os.environ.get(var):
            return val
    return None
