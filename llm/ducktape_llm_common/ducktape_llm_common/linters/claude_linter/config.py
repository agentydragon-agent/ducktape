import os
from pathlib import Path

import toml
import yaml

DEFAULT_CONFIG_PATH = Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config")) / "claude_linter" / "config.toml"
WHITELISTED_HOOKS = []  # TODO: populate with allowed hook IDs


def load_user_config():
    if DEFAULT_CONFIG_PATH.exists():
        return toml.load(DEFAULT_CONFIG_PATH)
    return {}


def load_local_precommit(path: Path) -> dict:
    local = path / ".pre-commit-config.yaml"
    if local.exists():
        return yaml.safe_load(local)
    return {}


def merge_configs(user_cfg: dict, local_cfg: dict) -> dict:
    # Merge user and local pre-commit configs, filter by whitelist
    merged = {"repos": []}
    for repo in local_cfg.get("repos", user_cfg.get("pre-commit", {}).get("repos", [])):
        filtered_hooks = []
        for hook in repo.get("hooks", []):
            if hook.get("id") in WHITELISTED_HOOKS:
                filtered_hooks.append(hook)
        if filtered_hooks:
            merged["repos"].append({"repo": repo["repo"], "rev": repo["rev"], "hooks": filtered_hooks})
    return merged


def get_merged_config(paths):
    user_cfg = load_user_config().get("pre-commit", {})
    local_cfg = {}
    for p in paths:
        cfg = load_local_precommit(Path(p).parent)
        if cfg:
            local_cfg = cfg
            break
    return merge_configs(user_cfg, local_cfg)
