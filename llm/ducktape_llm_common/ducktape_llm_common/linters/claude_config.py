"""Configuration models for Claude linter."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import platformdirs
from pydantic import BaseModel, Field


class RuleConfig(BaseModel):
    """Configuration for a specific linting rule."""

    enabled: bool = True
    severity: str = Field(default="error", pattern="^(error|warning|info)$")


class RuffConfig(BaseModel):
    """Configuration for ruff-based rules."""

    # Ruff rules to enable - NO DEFAULTS!
    enabled_rules: list[str] = Field(
        default_factory=list,
        description="List of ruff rule IDs to enable",
    )

    # Manual checks (not ruff rules)
    check_hasattr: bool = True  # No ruff rule for hasattr yet
    check_string_building: bool = False  # Disabled for now
    check_disabled_linting: bool = False  # # type: ignore,


class ClaudeLinterConfig(BaseModel):
    """Main configuration for Claude linter."""

    enabled: bool = True  # Default to enabled for all Claude projects

    # Rule configurations
    rules: RuffConfig = Field(default_factory=RuffConfig)

    # Global settings
    ignore_paths: list[str] = Field(
        default_factory=lambda: [
            ".venv",
            "venv",
            "__pycache__",
            ".git",
            "node_modules",
            ".mypy_cache",
            ".pytest_cache",
        ],
    )

    # Ruff integration
    ruff_config_file: str | None = None  # Path to ruff config

    # Output settings
    max_errors_per_file: int = 5
    show_context_lines: int = 2

    @classmethod
    def from_file(cls, path: Path) -> "ClaudeLinterConfig":
        """Load config from file (JSON or TOML)."""
        if not path.exists():
            return cls()

        if path.suffix == ".json":
            with open(path) as f:
                data = json.load(f)
                return cls(**data)

        elif path.suffix == ".toml":
            try:
                import tomllib
            except ImportError:
                import tomli as tomllib

            with open(path, "rb") as f:
                data = tomllib.load(f)
                # Handle [tool.claude-linter] section
                if "tool" in data and "claude-linter" in data["tool"]:
                    return cls(**data["tool"]["claude-linter"])
                return cls(**data)

        return cls()

    @classmethod
    def load_xdg_config(cls) -> dict[str, Any] | None:
        """Load user config from XDG config directory."""
        config_dir = Path(platformdirs.user_config_dir("claude-linter"))
        config_path = config_dir / "config.toml"

        if not config_path.exists():
            return None

        try:
            import tomllib
        except ImportError:
            import tomli as tomllib

        with open(config_path, "rb") as f:
            return tomllib.load(f)

    @classmethod
    def load_project_ruff_config(cls, start_path: Path) -> dict[str, Any] | None:
        """Load ruff configuration from project files."""
        config_names = [
            ("pyproject.toml", ["tool", "ruff"]),
            ("ruff.toml", []),
            (".ruff.toml", []),
        ]

        current = start_path.resolve()

        # Walk up directory tree to find git root
        while current != current.parent:
            # Check for config files
            for config_name, path_parts in config_names:
                config_path = current / config_name
                if config_path.exists():
                    try:
                        import tomllib
                    except ImportError:
                        import tomli as tomllib

                    with open(config_path, "rb") as f:
                        data = tomllib.load(f)

                    # Navigate to the right section
                    for part in path_parts:
                        if part in data:
                            data = data[part]
                        else:
                            data = None
                            break

                    if data:
                        return data

            # Stop at git root
            if (current / ".git").exists():
                break

            current = current.parent

        return None

    @classmethod
    def find_config(cls, start_path: Path | None = None) -> "ClaudeLinterConfig":
        """Find and load config file starting from given path."""
        if start_path is None:
            start_path = Path.cwd()

        disable_markers = [
            ".claude-linter-disable",
            ".no-claude-linter",
        ]

        current = start_path.resolve()

        # Check for explicit disable markers
        while current != current.parent:
            for disable_marker in disable_markers:
                if (current / disable_marker).exists():
                    return cls(enabled=False)  # Explicitly disabled
            if (current / ".git").exists():
                break
            current = current.parent

        # Load configurations in order
        # 1. Load XDG user config
        xdg_config = cls.load_xdg_config()
        user_ruff_rules = []
        if xdg_config and "ruff" in xdg_config:
            ruff_section = xdg_config["ruff"]
            # Support both "force-select" and "select" for user rules
            user_ruff_rules = ruff_section.get("force-select", ruff_section.get("select", []))

        # 2. Load project ruff config
        project_config = cls.load_project_ruff_config(start_path)
        project_ruff_rules = []
        if project_config:
            # Get rules from project's ruff config
            project_ruff_rules = project_config.get("select", [])
            # Also check for extend-select
            project_ruff_rules.extend(project_config.get("extend-select", []))

        # 3. Merge rules - user rules always included
        all_rules = list(set(user_ruff_rules + project_ruff_rules))

        # 4. Check if we have any configuration at all
        if not all_rules:
            # No config found anywhere
            raise ValueError(
                "No linter configuration found!\n\n"
                "claude-linter requires either:\n"
                "- A project ruff configuration ([tool.ruff] in pyproject.toml)\n"
                f"- Your personal config at {platformdirs.user_config_dir('claude-linter')}/config.toml\n\n"
                "Example personal config:\n"
                "[ruff]\n"
                'select = ["E", "F", "RET505", "B009"]\n',
            )

        # Create config with merged rules
        config = cls()
        config.rules.enabled_rules = all_rules
        return config

    def to_json_file(self, path: Path):
        """Save config to JSON file."""
        with open(path, "w") as f:
            f.write(self.model_dump_json(indent=2))


class ViolationDetail(BaseModel):
    """Details of a single violation."""

    line: int
    column: int
    rule: str
    message: str


class FileViolations(BaseModel):
    """Violations for a single file."""

    path: str
    violation_count: int
    violations: list[ViolationDetail]


class LinterReport(BaseModel):
    """Full linter report for all violations."""

    timestamp: datetime
    session_pid: int
    total_files: int
    total_violations: int
    violations_by_rule: dict[str, int]
    files: list[FileViolations]

    def to_json_file(self, path: Path):
        """Save report to JSON file."""
        with open(path, "w") as f:
            f.write(self.model_dump_json(indent=2))


class AutofixEntry(BaseModel):
    """Single autofix operation on a file."""

    file_path: str
    timestamp: datetime
    fix_type: str  # e.g. "ruff format", "ruff fix", "black", "trailing whitespace"
    rule_codes: list[str] | None = None  # Specific rules that were fixed
    before_snapshot: str  # Content before fix
    after_snapshot: str  # Content after fix
    diff_summary: str | None = None  # Summary of changes


class AutofixLog(BaseModel):
    """Log of all autofix operations in a session."""

    session_pid: int
    timestamp: datetime
    directory: str
    fixes: list[AutofixEntry]

    def to_json_file(self, path: Path):
        """Save autofix log to JSON file."""
        with open(path, "w") as f:
            f.write(self.model_dump_json(indent=2))
