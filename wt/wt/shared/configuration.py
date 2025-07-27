"""Runtime configuration with logic and resolvers.

THIS LOADS THE DATA AND RESOLVES IT INTO USEFUL THINGS FOR RUNTIME

This module contains the Configuration class that wraps the pure data
from ConfigFile and adds business logic, path resolution, validation,
and computed properties needed at runtime.

For the pure serializable data model, see config_file.py.
"""

import os
from pathlib import Path
from typing import Optional

import yaml

from .config_file import ConfigFile
from .directories import Directories


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
                main_repo = os.getenv("ADGN_MAIN_REPO")
                if not main_repo:
                    raise RuntimeError("main_repo not set in config and ADGN_MAIN_REPO not in environment")
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