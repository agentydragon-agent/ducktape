import os
import sys
from pathlib import Path

import click
import pygit2
import yaml
from platformdirs import user_config_dir
from pydantic import BaseModel, Field, ValidationError, field_validator

from .directories import Directories


class Config(BaseModel):
    """Configuration object that holds file config and resolves runtime values."""

    model_config = {"arbitrary_types_allowed": True}

    # File configuration fields (as loaded from YAML)
    main_repo: Path | None = None  # Auto-discovered if None
    worktrees_dir: Path | None = None  # Auto-discovered if None (main_repo/worktrees)
    branch_prefix: str  # Branch prefix for worktrees (required)
    default_worktree_base_branch: str  # Branch to create new worktrees from (required)
    log_operations: bool = True
    cow_method: str = "auto"  # 'auto', 'clonefile', 'reflink', 'rsync'
    github_repo: str   # GitHub repository name for PR operations
    github_enabled: bool = True  # Enable GitHub integration (disable for tests)
    cache_expiration: int = 1800  # Cache expiration time in seconds (30 minutes)
    cache_refresh_age: int = 300  # Background refresh age in seconds (5 minutes)
    hidden_worktree_patterns: list[str] = Field(
        default_factory=list
    )  # Patterns to filter hidden worktrees
    enable_git_fallbacks: bool = (
        False  # Enable fallback to git when gitstatusd fails (disabled by default)
    )
    # GitHub refresh system configuration
    github_debounce_delay: float = (
        5.0  # Seconds to wait after last git change before refreshing PR info
    )
    github_periodic_interval: float = 60.0  # Seconds between periodic GitHub refresh
    gitstatusd_path: str | None = None  # Path to gitstatusd binary (auto-detect if None)
    directories: Directories = Field(default_factory=lambda: Directories())

    # Private field to cache discovered main repo
    discovered_main_repo: Path | None = Field(default=None, exclude=True)

    @field_validator("main_repo", "worktrees_dir", mode="before")
    @classmethod
    def validate_absolute_paths(cls, v):
        """Ensure all path fields are absolute paths."""
        if v is None:
            return v
        path = Path(v)
        if not path.is_absolute():
            raise ValueError(f"Path must be absolute, got: {v}")
        return path

    @field_validator("gitstatusd_path", mode="before")
    @classmethod
    def validate_gitstatusd_path(cls, v):
        """Ensure gitstatusd path is absolute if provided."""
        if v is None:
            return v
        path = Path(v)
        if not path.is_absolute():
            raise ValueError(f"gitstatusd_path must be absolute, got: {v}")
        return str(path)  # Keep as string for this field

    @property
    def main_repo_resolved(self) -> Path:
        """Get resolved main repository path."""
        if self.main_repo is not None:
            return self.main_repo
        if self.discovered_main_repo is not None:
            return self.discovered_main_repo
        # Do discovery and cache result
        self.discovered_main_repo = _discover_main_repo()
        return self.discovered_main_repo

    @property
    def worktrees_dir_resolved(self) -> Path | None:
        """Get resolved worktrees directory path."""
        return self.worktrees_dir

    @property
    def daemon_dir(self) -> Path:
        """Get daemon directory path."""
        return self.main_repo_resolved / ".wt"

    @property
    def daemon_pid_file(self) -> Path:
        """Get daemon PID file path."""
        return self.daemon_dir / "daemon.pid"

    @property
    def daemon_socket_file(self) -> Path:
        """Get daemon socket file path.

        CRITICAL: Unix Socket Path Length Handling
        ==========================================

        Unix domain sockets have a path length limit of ~104 characters on most systems.
        This became a major issue during testing because pytest generates extremely long
        temporary directory paths like:

            /private/var/folders/_l/.../pytest-of-user/pytest-N/test_name0/test_repo/.wt/daemon.sock

        These paths (160+ chars) exceed the Unix socket limit, causing daemon startup
        to fail with "OSError: AF_UNIX path too long".

        SOLUTION: Automatically detect long paths and fall back to shorter paths in /tmp
        with MD5 hashing for uniqueness. This maintains daemon functionality while
        avoiding the Unix socket limitation.

        The fallback pattern is: /tmp/wt_daemon_{8-char-hash}.sock
        """
        normal_path = self.daemon_dir / "daemon.sock"

        # Unix socket path length limit is ~104 characters on most systems
        if len(str(normal_path)) <= 100:
            return normal_path

        # Use shorter path in /tmp with hash of main repo path for uniqueness
        import hashlib

        repo_hash = hashlib.md5(str(self.main_repo_resolved).encode()).hexdigest()[:8]
        short_path = Path(f"/tmp/wt_daemon_{repo_hash}.sock")
        return short_path


def _discover_main_repo() -> Path:
    """Discover main repository using the rationalized hierarchy:
    1. ADGN_MAIN_REPO env var (if set)
    2. Auto-detect from current directory's git repo using libgit2
    3. Error if no git repo found
    """
    # Priority 1: Explicit environment variable
    if main_repo := os.environ.get("ADGN_MAIN_REPO"):
        repo_path = Path(main_repo).expanduser()
        if not repo_path.is_absolute():
            click.echo(f"Error: ADGN_MAIN_REPO must be absolute path, got: {main_repo}")
            sys.exit(1)
        repo_path = repo_path.resolve()
        if not repo_path.exists():
            click.echo(f"Error: ADGN_MAIN_REPO points to non-existent path: {repo_path}")
            sys.exit(1)
        return repo_path

    # Priority 2: Auto-detect from current directory using libgit2
    current_dir = Path.cwd()
    while current_dir != current_dir.parent:
        try:
            # Try to open git repository at current directory using pygit2
            repo = pygit2.Repository(str(current_dir))

            # Get the repository workdir (main repo path)
            # For worktrees, this will point to the main repository location
            if repo.workdir:
                main_repo_path = Path(repo.workdir).resolve()
                return main_repo_path
            else:
                # Bare repository - use the git directory's parent
                return Path(repo.path).parent.resolve()

        except (pygit2.GitError, OSError):
            # Not a git repository, try parent directory
            current_dir = current_dir.parent
            continue

    # Priority 3: Error if no git repo found
    click.echo(
        "Error: No git repository found. Please run this command from within a git repository or set ADGN_MAIN_REPO."
    )
    sys.exit(1)


def load_config() -> Config:
    """Load configuration using the rationalized discovery hierarchy."""
    # Step 1: Discover the main repository
    main_repo = _discover_main_repo()

    # Step 2: Config file is always in {main_repo}/.wt/config.yaml
    config_dir = main_repo / ".wt"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "config.yaml"

    # Step 3: Load configuration file (required)
    try:
        with config_file.open() as f:
            file_config = yaml.safe_load(f) or {}
    except FileNotFoundError:
        click.echo(f"Error: Config file not found: {config_file}")
        click.echo("Please create a configuration file with required settings.")
        sys.exit(1)
    except Exception as e:
        click.echo(f"Error reading config file {config_file}: {e}")
        sys.exit(1)

    # Step 4: Validate the configuration
    try:
        config = Config.model_validate(file_config)
    except ValidationError as e:
        click.echo(f"Configuration validation errors in {config_file}:")
        for error in e.errors():
            field = ".".join(str(loc) for loc in error["loc"])
            click.echo(f"  {field}: {error['msg']}")
        click.echo(f"\nPlease fix the configuration file: {config_file}")
        sys.exit(1)

    # Step 5: Initialize directories using resolved paths
    config.directories.init_dirs()

    return config
