"""Immutable configuration after resolution.

This module contains the frozen Configuration dataclass that represents
resolved configuration with all paths validated and computed upfront.
"""

import os
import sys
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
from pathlib import Path

import click
import yaml
from pydantic import ValidationError

from .config_file import ConfigFile


class CowMethod(Enum):
    """Copy-on-write methods for worktree hydration."""
    AUTO = "auto"
    REFLINK = "reflink"
    COPY = "copy"
    RSYNC = "rsync"


class ConfigError(Exception):
    """Configuration validation or loading error."""


@dataclass(frozen=True)
class Configuration:
    """Immutable configuration after resolution."""
    wt_dir: Path
    main_repo: Path
    worktrees_dir: Path
    branch_prefix: str
    upstream_branch: str
    github_repo: str
    github_enabled: bool
    log_operations: bool
    cow_method: CowMethod
    gitstatusd_path: Path | None
    post_creation_script: Path | None
    cache_expiration: timedelta
    cache_refresh_age: timedelta
    hidden_worktree_patterns: list[str]
    github_debounce_delay: timedelta
    github_periodic_interval: timedelta
    
    @property
    def daemon_socket_path(self) -> Path:
        """Path to daemon socket file."""
        return self.wt_dir / "daemon.sock"
    
    @property
    def daemon_pid_path(self) -> Path:
        """Path to daemon PID file.""" 
        return self.wt_dir / "daemon.pid"
    
    @property
    def operations_log_file(self) -> Path:
        """Path to operations log file."""
        return self.wt_dir / "operations.log"
    
    @property
    def pr_cache_file(self) -> Path:
        """Path to PR cache file."""
        return self.wt_dir / "pr_cache.json"
    
    # Legacy property aliases for compatibility during transition
    @property
    def main_repo_resolved(self) -> Path:
        """Legacy alias for main_repo."""
        return self.main_repo
    
    @property
    def worktrees_dir_resolved(self) -> Path:
        """Legacy alias for worktrees_dir."""
        return self.worktrees_dir
    
    @property
    def daemon_dir(self) -> Path:
        """Legacy alias for wt_dir."""
        return self.wt_dir
    
    @property
    def daemon_socket_file(self) -> Path:
        """Legacy alias for daemon_socket_path."""
        return self.daemon_socket_path
    
    @property
    def daemon_pid_file(self) -> Path:
        """Legacy alias for daemon_pid_path."""
        return self.daemon_pid_path
    
    @classmethod
    def resolve(cls, wt_dir: Path) -> "Configuration":
        """Resolve configuration from WT_DIR - does all filesystem validation upfront."""
        config_path = wt_dir / "config.yaml"
        
        if not config_path.exists():
            raise ConfigError(f"Config file not found: {config_path}")
            
        with open(config_path) as f:
            data = yaml.safe_load(f)
        
        try:
            config_file = ConfigFile(**data)  # Pydantic validation
        except ValidationError as e:
            raise ConfigError(f"Configuration validation errors: {e}")
        
        # Resolve and validate all paths NOW
        main_repo = Path(config_file.main_repo).expanduser().resolve()
        if not main_repo.exists():
            raise ConfigError(f"Main repo not found: {main_repo}")
        if not (main_repo / ".git").exists():
            raise ConfigError(f"Not a git repository: {main_repo}")
            
        worktrees_dir = Path(config_file.worktrees_dir).expanduser().resolve()
        
        # Resolve optional paths
        gitstatusd_path = None
        if config_file.gitstatusd_path:
            gitstatusd_path = Path(config_file.gitstatusd_path).expanduser().resolve()
        
        post_creation_script = None
        if config_file.post_creation_script:
            post_creation_script = Path(config_file.post_creation_script).expanduser().resolve()
        
        return cls(
            wt_dir=wt_dir,
            main_repo=main_repo,
            worktrees_dir=worktrees_dir,
            branch_prefix=config_file.branch_prefix,
            upstream_branch=config_file.upstream_branch,
            github_repo=config_file.github_repo,
            github_enabled=config_file.github_enabled,
            log_operations=config_file.log_operations,
            cow_method=CowMethod(config_file.cow_method),
            gitstatusd_path=gitstatusd_path,
            post_creation_script=post_creation_script,
            cache_expiration=timedelta(seconds=config_file.cache_expiration),
            cache_refresh_age=timedelta(seconds=config_file.cache_refresh_age),
            hidden_worktree_patterns=config_file.hidden_worktree_patterns.copy(),
            github_debounce_delay=timedelta(seconds=config_file.github_debounce_delay),
            github_periodic_interval=timedelta(seconds=config_file.github_periodic_interval),
        )


def load_config() -> Configuration:
    """Load configuration from WT_DIR environment variable."""
    wt_dir_env = os.getenv("WT_DIR")
    if not wt_dir_env:
        click.echo("Error: WT_DIR environment variable must be set")
        sys.exit(1)
    
    wt_dir = Path(wt_dir_env).expanduser().resolve()
    if not wt_dir.exists():
        click.echo(f"Error: WT_DIR does not exist: {wt_dir}")
        sys.exit(1)
        
    try:
        return Configuration.resolve(wt_dir)
    except ConfigError as e:
        click.echo(f"Configuration error: {e}")
        sys.exit(1)


