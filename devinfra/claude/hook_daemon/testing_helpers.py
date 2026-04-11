"""Shared test helpers for hook daemon tests."""

from pathlib import Path

import yaml

from devinfra.claude.hook_daemon.config import DefaultProfiles, HookConfig, ProfileConfig
from devinfra.claude.session_paths import SessionPaths

TEST_HOOK_CONFIG = HookConfig(
    profiles={"default": ProfileConfig()}, default_profiles=DefaultProfiles(cli="default", web="default")
)


def setup_daemon_project(base_dir: Path, paths: SessionPaths) -> tuple[Path, Path]:
    """Create minimal project dir with hook config and return (project_dir, env_file).

    Used by both the daemon_paths fixture and test_parallel_cold_start (which needs
    os.environ for child process inheritance instead of monkeypatch).
    """
    project_dir = base_dir / "project"
    project_dir.mkdir(exist_ok=True)
    hooks_dir = project_dir / ".claude_hooks"
    hooks_dir.mkdir(exist_ok=True)
    (hooks_dir / "config.yaml").write_text(yaml.dump(TEST_HOOK_CONFIG.model_dump(mode="json")))
    env_file = paths.session_dir / "sessionstart-hook-0.sh"
    return project_dir, env_file
