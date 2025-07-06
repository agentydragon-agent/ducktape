"""Configuration models for Claude Linter v2 using Pydantic."""

from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class Violation(BaseModel):
    """A code quality violation."""

    rule: str = Field(description="Rule identifier (e.g., 'bare_except', 'ruff:E722')")
    line: int = Field(description="Line number where violation occurs")
    column: int = Field(0, description="Column number (optional)")
    message: str = Field(description="Human-readable violation message")
    fixable: bool = Field(False, description="Whether this can be auto-fixed")


class HookType(str, Enum):
    """Types of Claude Code hooks."""

    PRE = "pre"
    POST = "post"
    STOP = "stop"


class RuleAction(str, Enum):
    """Actions that can be taken by rules."""

    ALLOW = "allow"
    DENY = "deny"
    WARN = "warn"


class AutofixCategory(str, Enum):
    """Categories of autofixes."""

    FORMATTING = "formatting"
    IMPORTS = "imports"
    TYPE_HINTS = "type_hints"
    SECURITY = "security"
    ALL = "all"


class AccessControlRule(BaseModel):
    """Path-based access control rule."""

    paths: list[str] = Field(description="Glob patterns for paths")
    tools: list[str] = Field(description="Tool names (Write, Edit, etc)")
    action: RuleAction = Field(description="Action to take")
    message: str | None = Field(None, description="Custom message to show")


class PredicateRule(BaseModel):
    """Python predicate-based rule."""

    predicate: str = Field(description="Python expression or function")
    action: RuleAction = Field(description="Action to take")
    message: str | None = Field(None, description="Custom message to show")
    priority: int = Field(0, description="Rule priority (higher = evaluated first)")


class CheckConfig(BaseModel):
    """Configuration for a single check."""

    enabled: bool = Field(True, description="Whether this check is enabled")
    message: str | None = Field(None, description="Custom error message")
    severity: Literal["error", "warning", "info"] = Field("error", description="Severity level")


class PythonHardBlock(BaseModel):
    """Python AST-based hard block configuration."""

    bare_except: bool = Field(True, description="Block bare except clauses")
    getattr_setattr: bool = Field(True, description="Block hasattr/getattr/setattr usage")
    barrel_init: bool = Field(True, description="Block barrel __init__.py patterns")


class PythonConfig(BaseModel):
    """Python-specific linting configuration."""

    tools: list[str] = Field(default_factory=lambda: ["ruff", "mypy"], description="Python linting tools to use")
    hard_blocks: PythonHardBlock = Field(default_factory=lambda: PythonHardBlock(), description="AST-based hard blocks")

    # Ruff configuration
    ruff_force_select: list[str] = Field(
        default_factory=lambda: [
            # Critical rules that should always be checked
            "E722",  # bare-except
            "BLE001",  # blind-except
            "B009",  # getattr-with-constant
            "B010",  # setattr-with-constant
            "S113",  # request-without-timeout
            "B008",  # function-call-in-default-argument
            "E402",  # module-import-not-at-top-of-file
            "PLC0415",  # import-outside-top-level
            "S608",  # hardcoded-sql-expression
            "B904",  # raise-without-from-inside-except
            "B006",  # mutable-argument-default
            "PGH003",  # blanket-type-ignore
        ],
        description="Ruff rules to force enable",
    )

    # Test file handling
    test_patterns: list[str] = Field(
        default_factory=lambda: ["**/test_*.py", "**/*_test.py", "**/tests/**/*.py"],
        description="Patterns to identify test files",
    )
    relaxed_rules_for_tests: list[str] = Field(
        default_factory=lambda: ["bare_except", "type_checking"], description="Rules to relax for test files"
    )


class HookConfig(BaseModel):
    """Configuration for a specific hook type."""

    auto_fix: bool = Field(True, description="Whether to auto-fix issues")
    autofix_categories: list[AutofixCategory] = Field(
        default_factory=list, description="Categories to autofix (empty = use defaults)"
    )
    inject_permissions: bool = Field(True, description="Whether to inject permission info in responses")
    quality_gate: bool = Field(False, description="Whether to enforce quality gate (Stop hook only)")

    @field_validator("autofix_categories", mode="before")
    @classmethod
    def expand_all_category(cls, v: list[Any]) -> list[AutofixCategory]:
        """Expand 'all' category to all categories."""
        if not v:
            return []

        categories = []
        for cat in v:
            if isinstance(cat, str):
                cat = AutofixCategory(cat)
            if cat == AutofixCategory.ALL:
                return list(AutofixCategory)
            categories.append(cat)

        return categories


class LLMAnalysisConfig(BaseModel):
    """Configuration for LLM-based analysis."""

    enabled: bool = Field(False, description="Whether to use LLM analysis")
    model: str = Field("gpt-4o-mini", description="Model to use")
    check_types: list[str] = Field(
        default_factory=lambda: ["error_hiding", "security_issues"], description="Types of checks to perform"
    )
    daily_cost_limit: float = Field(5.0, description="Maximum daily cost in USD")
    cache_results: bool = Field(True, description="Whether to cache results")


class TaskProfile(BaseModel):
    """Pre-approved permission profile for common tasks."""

    name: str = Field(description="Profile name")
    description: str | None = Field(None, description="Profile description")
    predicate: str = Field(description="Python predicate granting permissions")
    duration: str | None = Field(None, description="How long profile is active")

    @field_validator("duration")
    @classmethod
    def validate_duration(cls, v: str | None) -> str | None:
        """Validate duration format."""
        if v is None:
            return None

        # Simple validation - could be expanded
        import re

        if not re.match(r"^\d+[hmd]$", v):
            raise ValueError("Duration must be like '2h', '30m', or '1d'")

        return v


class ClaudeLinterConfig(BaseModel):
    """Main configuration for Claude Linter v2."""

    version: Literal["2.0"] = Field("2.0", description="Config version")

    # Display settings
    max_errors_to_show: int = Field(3, description="Maximum number of errors to display in hook responses")

    # Access control
    access_control: list[AccessControlRule] = Field(default_factory=list, description="Path-based access control rules")

    # Repo-wide predicate rules
    repo_rules: list[PredicateRule] = Field(default_factory=list, description="Repository-wide predicate rules")

    # Language-specific configs
    python: PythonConfig = Field(default_factory=lambda: PythonConfig(), description="Python-specific configuration")

    # Hook behaviors
    hooks: dict[str, HookConfig] = Field(
        default_factory=lambda: {
            "pre": HookConfig(auto_fix=False),
            "post": HookConfig(auto_fix=True, autofix_categories=[AutofixCategory.FORMATTING]),
            "stop": HookConfig(auto_fix=False, inject_permissions=False, quality_gate=True),
            "notification": HookConfig(auto_fix=False, inject_permissions=False),
            "subagent_stop": HookConfig(auto_fix=False, inject_permissions=False),
        },
        description="Hook-specific configurations",
    )

    # Test file handling
    test_patterns: list[str] = Field(
        default_factory=lambda: ["**/test_*.py", "**/*_test.py", "**/tests/**"], description="Global test file patterns"
    )

    # LLM analysis
    llm_analysis: LLMAnalysisConfig = Field(
        default_factory=lambda: LLMAnalysisConfig(), description="LLM analysis configuration"
    )

    # Task profiles
    profiles: list[TaskProfile] = Field(default_factory=list, description="Pre-defined permission profiles")

    # Logging
    log_level: str = Field("INFO", description="Logging level")
    log_file: Path | None = Field(None, description="Log file path")

    # Notifications
    send_notifications_to_dbus: bool = Field(
        False, description="Send Notification hook messages to D-Bus notifications"
    )

    @classmethod
    def load_from_file(cls, path: Path) -> "ClaudeLinterConfig":
        """Load configuration from TOML file."""
        import tomli

        with open(path, "rb") as f:
            data = tomli.load(f)

        return cls(**data)

    def save_to_file(self, path: Path) -> None:
        """Save configuration to TOML file."""
        import tomli_w

        # Convert to dict, handling enums and paths
        data = self.model_dump(mode="json")

        with open(path, "wb") as f:
            tomli_w.dump(data, f)
