"""Runtime configuration with logic and resolvers.

THIS LOADS THE DATA AND RESOLVES IT INTO USEFUL THINGS FOR RUNTIME

This module contains the Configuration class that wraps the pure data
from ConfigFile and adds business logic, path resolution, validation,
and computed properties needed at runtime.

For the pure serializable data model, see config_file.py.
"""

import os
import sys
from pathlib import Path
from typing import Optional

import click
import pygit2
import yaml
from pydantic import ValidationError

from .config_file import ConfigFile
from .directories import Directories


def load_config():
    """Load configuration using simplified WT_MAIN_REPO -> .wt/config.yaml path."""
    # Step 1: Get main repository from WT_MAIN_REPO (only supported method)
    main_repo_env = os.getenv("WT_MAIN_REPO")
    if not main_repo_env:
        click.echo("Error: WT_MAIN_REPO environment variable must be set")
        sys.exit(1)
    
    main_repo = Path(main_repo_env).expanduser().resolve()
    if not main_repo.exists():
        click.echo(f"Error: WT_MAIN_REPO points to non-existent path: {main_repo}")
        sys.exit(1)
    if not (main_repo / ".git").exists():
        click.echo(f"Error: WT_MAIN_REPO is not a git repository: {main_repo}")
        sys.exit(1)

    # Step 2: Config file is always in {main_repo}/.wt/config.yaml
    config_dir = main_repo / ".wt"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "config.yaml"

    # Step 3: Load configuration using Configuration class
    try:
        directories = Directories()
        directories.init_dirs()
        
        config = Configuration.load_from_file(config_file, directories)
        return config
    except FileNotFoundError:
        click.echo(f"Error: Config file not found: {config_file}")
        click.echo("Please create a configuration file with required settings.")
        sys.exit(1)
    except ValidationError as e:
        click.echo(f"Configuration validation errors in {config_file}:")
        for error in e.errors():
            field = ".".join(str(loc) for loc in error["loc"])
            click.echo(f"  {field}: {error['msg']}")
        click.echo(f"\nPlease fix the configuration file: {config_file}")
        sys.exit(1)
    except Exception as e:
        click.echo(f"Error loading config file {config_file}: {e}")
        sys.exit(1)


class Configuration:
    """Runtime configuration with logic and resolvers.
    
    THIS LOADS THE DATA AND RESOLVES IT INTO USEFUL THINGS FOR RUNTIME
    
    This class wraps ConfigFile and adds:
    - Path resolution and validation
    - Environment variable handling  
    - Computed properties
    - Runtime dependencies like Directories
    - Business logic and validation
    """
    
    def __init__(self, config_file: ConfigFile, directories: Optional[Directories] = None):
        self._config_file = config_file
        self._directories = directories or Directories()
        self._resolved_paths = {}  # Cache for resolved paths
    
    @classmethod
    def load_from_file(cls, config_path: Path, directories: Optional[Directories] = None) -> "Configuration":
        """Load configuration from YAML file."""
        with open(config_path, 'r') as f:
            data = yaml.safe_load(f) or {}
        
        config_file = ConfigFile(**data)
        return cls(config_file, directories)
    
    @classmethod
    def load_from_main_repo(cls, main_repo_path: Path, directories: Optional[Directories] = None) -> "Configuration":
        """Load configuration from main repo's .wt/config.yaml."""
        config_path = main_repo_path / ".wt" / "config.yaml"
        return cls.load_from_file(config_path, directories)
    
    # Raw data access
    @property
    def config_file(self) -> ConfigFile:
        """Access to the raw configuration data."""
        return self._config_file
    
    @property
    def directories(self) -> Directories:
        """Runtime directories helper."""
        return self._directories
    
    # Resolved path properties
    @property
    def main_repo_resolved(self) -> Path:
        """Resolved path to main repository."""
        if "main_repo" not in self._resolved_paths:
            if self._config_file.main_repo:
                path = Path(self._config_file.main_repo).expanduser().resolve()
            else:
                # Auto-discover from environment
                main_repo = os.getenv("WT_MAIN_REPO")
                if not main_repo:
                    raise RuntimeError("main_repo not set in config and WT_MAIN_REPO not in environment")
                path = Path(main_repo).expanduser().resolve()
            
            if not path.exists():
                raise RuntimeError(f"Main repository not found: {path}")
            if not (path / ".git").exists():
                raise RuntimeError(f"Path is not a git repository: {path}")
                
            self._resolved_paths["main_repo"] = path
        
        return self._resolved_paths["main_repo"]
    
    @property
    def worktrees_dir_resolved(self) -> Path:
        """Resolved path to worktrees directory."""
        if "worktrees_dir" not in self._resolved_paths:
            # Handle both absolute and relative paths
            worktrees_path = Path(self._config_file.worktrees_dir)
            if not worktrees_path.is_absolute():
                # Relative to main repo
                worktrees_path = self.main_repo_resolved / worktrees_path
            
            path = worktrees_path.expanduser().resolve()
            self._resolved_paths["worktrees_dir"] = path
        
        return self._resolved_paths["worktrees_dir"]
    
    @property 
    def gitstatusd_path_resolved(self) -> Optional[Path]:
        """Resolved path to gitstatusd binary."""
        if not self._config_file.gitstatusd_path:
            return None
        return Path(self._config_file.gitstatusd_path).expanduser().resolve()
    
    # Daemon paths (computed from directories)
    @property
    def daemon_dir(self) -> Path:
        """Directory for daemon files."""
        return self._directories.runtime_dir
    
    @property
    def daemon_pid_file(self) -> Path:
        """Path to daemon PID file."""
        return self.daemon_dir / "daemon.pid"
    
    @property
    def daemon_socket_file(self) -> Path:
        """Path to daemon socket file."""
        return self.daemon_dir / "daemon.sock"
    
    # Simple property forwarding
    @property
    def branch_prefix(self) -> str:
        return self._config_file.branch_prefix
    
    @property
    def default_worktree_base_branch(self) -> str:
        return self._config_file.default_worktree_base_branch
    
    @property
    def log_operations(self) -> bool:
        return self._config_file.log_operations
    
    @property
    def cow_method(self) -> str:
        return self._config_file.cow_method
    
    @property
    def github_enabled(self) -> bool:
        return self._config_file.github_enabled
    
    @property
    def github_repo(self) -> str:
        return self._config_file.github_repo
    
    @property
    def cache_expiration(self) -> int:
        return self._config_file.cache_expiration
    
    @property
    def cache_refresh_age(self) -> int:
        return self._config_file.cache_refresh_age
    
    @property
    def hidden_worktree_patterns(self) -> list[str]:
        return self._config_file.hidden_worktree_patterns
    
    @property
    def github_debounce_delay(self) -> float:
        return self._config_file.github_debounce_delay
    
    @property
    def github_periodic_interval(self) -> float:
        return self._config_file.github_periodic_interval
    
    @property
    def post_creation_script(self) -> Optional[str]:
        return self._config_file.post_creation_script