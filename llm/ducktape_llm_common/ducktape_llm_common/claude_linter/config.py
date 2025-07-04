import json
import os
from pathlib import Path

import platformdirs
import toml
import yaml

DEFAULT_CONFIG_PATH = Path(platformdirs.user_config_dir("claude-linter")) / "config.toml"


def load_user_config():
    # Allow tests to disable loading user config
    if os.getenv("CLAUDE_LINTER_NO_USER_CONFIG"):
        return {}

    if DEFAULT_CONFIG_PATH.exists():
        # Convert toml data to plain dict to avoid yaml serialization issues
        data = toml.load(DEFAULT_CONFIG_PATH)
        return json.loads(json.dumps(data))
    return {}


def load_local_precommit(path: Path) -> dict:
    local = path / ".pre-commit-config.yaml"
    if local.exists():
        with open(local) as f:
            return yaml.safe_load(f)
    return {}


def merge_configs(user_cfg: dict, local_cfg: dict, fix: bool) -> dict:
    merged: dict[str, list] = {"repos": []}

    # Start with user's pre-commit repos if provided
    if fix and "repos" in user_cfg:
        merged["repos"].extend(user_cfg["repos"])

    # Then add local repos
    repos = local_cfg.get("repos", [])

    for repo in repos:
        # Include all repos regardless of fix parameter
        # The fix behavior is now controlled in PreCommitRunner
        merged["repos"].append(repo)

    # Copy any other top-level pre-commit config keys
    for key in local_cfg:
        if key != "repos":
            merged[key] = local_cfg[key]

    return merged


def get_merged_config(paths, fix=False):
    user_config = load_user_config()
    # Get the pre-commit section, which contains repos array
    user_pre_commit = user_config.get("pre-commit", {})

    local_cfg = {}
    for p in paths:
        # We need to find the .pre-commit-config.yaml, which could be in a parent directory
        path = Path(p)
        while path.parent != path:
            cfg = load_local_precommit(path)
            if cfg:
                local_cfg = cfg
                break
            path = path.parent
        if local_cfg:
            break

    return merge_configs(user_pre_commit, local_cfg, fix=fix)
