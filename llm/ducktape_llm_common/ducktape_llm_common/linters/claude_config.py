"""Configuration models for Claude linter."""

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field


class RuleConfig(BaseModel):
    """Configuration for a specific linting rule."""

    enabled: bool = True
    severity: str = Field(default="error", pattern="^(error|warning|info)$")


class RuffConfig(BaseModel):
    """Configuration for ruff-based rules."""

    # Ruff rules to enable
    enabled_rules: list[str] = Field(
        default_factory=lambda: [
            # Early bailout patterns
            "RET505",  # superfluous-else-return (autofix available)
            "RET506",  # superfluous-else-raise (autofix available)
            "RET507",  # superfluous-else-continue (autofix available)
            "RET508",  # superfluous-else-break (autofix available)
            "PLR5501",  # collapsible-else-if (autofix available)
            "SIM102",  # collapsible-if (autofix available)
            # CLAUDE.md: /attrs/no-hasattr-getattr
            "B009",  # getattr-with-constant (autofix available)
            "B010",  # setattr-with-constant (autofix available)
            # Modern Python features
            "UP007",  # non-pep604-annotation-union (X | Y) (autofix available)
            "UP032",  # f-string (autofix available)
            "RUF013",  # implicit-optional (autofix available)
            "UP018",  # native-literals (autofix available)
            "UP009",  # utf8-encoding-declaration (autofix available)
            "UP010",  # unnecessary-future-import (autofix available)
            # Timeout patterns for blocking operations
            "S113",  # request-without-timeout
            "ASYNC109",  # async-function-with-timeout
            # Function call in default arguments
            "B008",  # function-call-in-default-argument
            # Simplify code patterns
            "SIM108",  # if-else-block-instead-of-if-exp (autofix available)
            "SIM110",  # reimplemented-builtin (autofix available)
            "SIM114",  # if-with-same-arms (autofix available)
            "SIM118",  # in-dict-keys (autofix available)
            "PLR1714",  # repeated-equality-comparison (autofix available)
            # Remove redundant code
            "RUF100",  # unused-noqa (autofix available)
            "PLR1711",  # useless-return (autofix available)
            "RET501",  # unnecessary-return-none (autofix available)
            "RET502",  # implicit-return-value (autofix available)
            "RET504",  # unnecessary-assign (autofix available)
            # Path and imports best practices
            "S108",  # hardcoded-temp-file
            "E402",  # module-import-not-at-top-of-file
            # Documentation rules (no redundant docs)
            "D200",  # unnecessary-multiline-docstring (autofix available)
            # String building for URLs/SQL/HTML
            "S608",  # hardcoded-sql-expression
            "S611",  # django-raw-sql
            # CLAUDE.md: /errors/fail-fast
            "E722",  # bare-except
            "BLE001",  # blind-except
            # Error handling
            "B904",  # raise-without-from-inside-except
            # Code quality
            "B002",  # unary-prefix-increment-decrement
            "B003",  # assignment-to-os-environ
            "B006",  # mutable-argument-default
            "B011",  # assert-false
            "B018",  # useless-expression
            "PIE810",  # multiple-starts-ends-with
            # CLAUDE.md: Use modern Python features (legacy)
            "UP006",  # use-union-operator (X | Y) (autofix sometimes)
            "UP035",  # deprecated-typing-import (autofix sometimes)
            # CLAUDE.md: Code style
            "W291",  # trailing-whitespace (autofix available)
            # CLAUDE.md: Python conventions
            "PTH100",
            "PTH101",
            "PTH102",
            "PTH103",  # use-pathlib rules
            # CLAUDE.md: /data/no-data-loss
            "E999",  # syntax-error (ensure files parse)
        ],
        description="List of ruff rule IDs to enable",
    )

    # Manual checks (not ruff rules)
    check_hasattr: bool = True  # No ruff rule for hasattr yet
    check_string_building: bool = False  # Disabled for now
    check_disabled_linting: bool = False  # # type: ignore, # noqa - disabled for now


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
        ]
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
            import json

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
    def find_config(cls, start_path: Path | None = None) -> "ClaudeLinterConfig":
        """Find and load config file starting from given path."""
        if start_path is None:
            start_path = Path.cwd()
        config_names = [
            ".claude-linter.json",
            ".claude/linter.json",
            "pyproject.toml",
        ]

        disable_markers = [
            ".claude-linter-disable",
            ".no-claude-linter",
        ]

        current = start_path.resolve()

        # Walk up directory tree
        while current != current.parent:
            # Check for explicit disable markers
            for disable_marker in disable_markers:
                if (current / disable_marker).exists():
                    return cls(enabled=False)  # Explicitly disabled

            # Check for config files
            for config_name in config_names:
                config_path = current / config_name
                if config_path.exists():
                    return cls.from_file(config_path)
            current = current.parent

        return cls()  # Default config (enabled by default)

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
