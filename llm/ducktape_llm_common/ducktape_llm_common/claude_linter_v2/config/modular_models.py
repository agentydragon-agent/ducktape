"""Modular configuration models for Claude Linter v2.

This module provides a more granular, modular configuration structure
where each check can be individually configured with its own section.
"""

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from .models import (
    AccessControlRule,
    AutofixCategory,
    LLMAnalysisConfig,
    NotificationHookConfig,
    PatternBasedRule,
    PostToolHookConfig,
    PredicateRule,
    PreToolHookConfig,
    StopHookConfig,
    SubagentStopHookConfig,
    TaskProfile,
)


class CheckConfigBase(BaseModel):
    """Base configuration for any check."""

    enabled: bool = Field(True, description="Whether this check is enabled")
    message: str | None = Field(None, description="Custom error message")
    severity: Literal["error", "warning", "info"] = Field("error", description="Severity level")
    autofix: bool | None = Field(None, description="Whether this can be auto-fixed")


class ModularClaudeLinterConfig(BaseModel):
    """Modular configuration for Claude Linter v2.

    This configuration style allows for more granular control where each
    check has its own configuration section.
    """

    version: Literal["2.0"] = Field("2.0", description="Config version")

    # Display settings
    max_errors_to_show: int = Field(3, description="Maximum number of errors to display in hook responses")

    # Access control
    access_control: list[AccessControlRule] = Field(default_factory=list, description="Path-based access control rules")

    # Repo-wide predicate rules
    repo_rules: list[PredicateRule] = Field(default_factory=list, description="Repository-wide predicate rules")

    # Python checks - each gets its own section
    python_bare_except: CheckConfigBase = Field(
        default_factory=lambda: CheckConfigBase(enabled=True, message="Bare except clauses hide errors"),
        alias="python.bare_except",
    )

    python_hasattr: CheckConfigBase = Field(
        default_factory=lambda: CheckConfigBase(enabled=True, message="hasattr() usage is discouraged"),
        alias="python.hasattr",
    )

    python_getattr: CheckConfigBase = Field(
        default_factory=lambda: CheckConfigBase(enabled=True, message="getattr() usage is discouraged"),
        alias="python.getattr",
    )

    python_setattr: CheckConfigBase = Field(
        default_factory=lambda: CheckConfigBase(enabled=True, message="setattr() usage is discouraged"),
        alias="python.setattr",
    )

    python_barrel_init: CheckConfigBase = Field(
        default_factory=lambda: CheckConfigBase(
            enabled=True, message="Barrel __init__.py files (with imports) are discouraged"
        ),
        alias="python.barrel_init",
    )

    # Python tools configuration
    python_tools: list[str] = Field(
        default_factory=lambda: ["ruff", "mypy"], description="Python linting tools to use", alias="python.tools"
    )

    # Ruff-specific checks
    ruff_e722: CheckConfigBase = Field(
        default_factory=lambda: CheckConfigBase(enabled=True, autofix=False),
        alias="ruff.E722",
        description="bare-except",
    )

    ruff_ble001: CheckConfigBase = Field(
        default_factory=lambda: CheckConfigBase(enabled=True, autofix=False),
        alias="ruff.BLE001",
        description="blind-except",
    )

    ruff_b009: CheckConfigBase = Field(
        default_factory=lambda: CheckConfigBase(enabled=True, autofix=False),
        alias="ruff.B009",
        description="getattr-with-constant",
    )

    ruff_b010: CheckConfigBase = Field(
        default_factory=lambda: CheckConfigBase(enabled=True, autofix=False),
        alias="ruff.B010",
        description="setattr-with-constant",
    )

    ruff_s113: CheckConfigBase = Field(
        default_factory=lambda: CheckConfigBase(enabled=True, severity="error"),
        alias="ruff.S113",
        description="request-without-timeout",
    )

    ruff_b008: CheckConfigBase = Field(
        default_factory=lambda: CheckConfigBase(enabled=True, autofix=True),
        alias="ruff.B008",
        description="function-call-in-default-argument",
    )

    ruff_e402: CheckConfigBase = Field(
        default_factory=lambda: CheckConfigBase(enabled=True, autofix=True),
        alias="ruff.E402",
        description="module-import-not-at-top-of-file",
    )

    ruff_plc0415: CheckConfigBase = Field(
        default_factory=lambda: CheckConfigBase(enabled=True, autofix=False),
        alias="ruff.PLC0415",
        description="import-outside-top-level",
    )

    ruff_s608: CheckConfigBase = Field(
        default_factory=lambda: CheckConfigBase(enabled=True, severity="error"),
        alias="ruff.S608",
        description="hardcoded-sql-expression",
    )

    ruff_b904: CheckConfigBase = Field(
        default_factory=lambda: CheckConfigBase(enabled=True, autofix=True),
        alias="ruff.B904",
        description="raise-without-from-inside-except",
    )

    ruff_b006: CheckConfigBase = Field(
        default_factory=lambda: CheckConfigBase(enabled=True, autofix=False),
        alias="ruff.B006",
        description="mutable-argument-default",
    )

    ruff_pgh003: CheckConfigBase = Field(
        default_factory=lambda: CheckConfigBase(enabled=True, severity="error"),
        alias="ruff.PGH003",
        description="blanket-type-ignore",
    )

    # Hook behaviors - each hook type has its own config class
    hooks: dict[
        str, PreToolHookConfig | PostToolHookConfig | StopHookConfig | NotificationHookConfig | SubagentStopHookConfig
    ] = Field(
        default_factory=lambda: {
            "pre": PreToolHookConfig(),
            "post": PostToolHookConfig(auto_fix=True, autofix_categories=[AutofixCategory.FORMATTING]),
            "stop": StopHookConfig(quality_gate=True),
            "notification": NotificationHookConfig(send_to_dbus=True),
            "subagent_stop": SubagentStopHookConfig(),
        },
        description="Hook-specific configurations",
    )

    # Pattern-based file rules (replaces test-specific handling)
    pattern_rules: list[PatternBasedRule] = Field(
        default_factory=lambda: [
            PatternBasedRule(
                name="test_files",
                patterns=["**/test_*.py", "**/*_test.py", "**/tests/**"],
                relaxed_checks=["python.bare_except", "ruff.E722"],
                custom_message="Test files have relaxed rules for error handling",
            )
        ],
        description="Pattern-based rules for file handling",
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

    model_config = {
        "populate_by_name": True,  # Allow field aliases
        "extra": "allow",  # Allow extra fields for custom rules
    }

    @model_validator(mode="after")
    def collect_dynamic_rules(self) -> "ModularClaudeLinterConfig":
        """Collect any dynamic rule configurations from extra fields."""
        # This allows users to define custom rules like:
        # [mypy.no_untyped_def]
        # enabled = true
        # message = "All functions must have type annotations"
        return self

    def get_check_config(self, check_name: str) -> CheckConfigBase | None:
        """Get configuration for a specific check.

        Args:
            check_name: Name like "python.bare_except" or "ruff.E722"

        Returns:
            Check configuration or None if not found
        """
        # Convert dots to underscores for attribute lookup
        attr_name = check_name.replace(".", "_").lower()

        # Try direct attribute lookup
        if hasattr(self, attr_name):
            value = getattr(self, attr_name)
            if isinstance(value, CheckConfigBase):
                return value

        # Try from extra fields
        extra = getattr(self, "__pydantic_extra__", {})
        if check_name in extra and isinstance(extra[check_name], dict):
            return CheckConfigBase(**extra[check_name])

        return None

    def is_check_enabled(self, check_name: str) -> bool:
        """Check if a specific check is enabled.

        Args:
            check_name: Name like "python.bare_except" or "ruff.E722"

        Returns:
            True if enabled, False otherwise
        """
        config = self.get_check_config(check_name)
        return config.enabled if config else False

    def get_ruff_force_select(self) -> list[str]:
        """Get list of ruff rules to force enable based on modular config."""
        force_select = []

        # Check all ruff rules
        for attr_name in dir(self):
            if attr_name.startswith("ruff_"):
                value = getattr(self, attr_name)
                if isinstance(value, CheckConfigBase) and value.enabled:
                    # Extract rule code from attribute name
                    rule_code = attr_name[5:].upper().replace("_", "")
                    force_select.append(rule_code)

        # Also check extra fields
        extra = getattr(self, "__pydantic_extra__", {})
        for key, value in extra.items():
            if key.startswith("ruff.") and isinstance(value, dict):
                if value.get("enabled", True):
                    rule_code = key[5:]  # Remove "ruff." prefix
                    force_select.append(rule_code)

        return force_select

    @classmethod
    def load_from_file(cls, path: Path) -> "ModularClaudeLinterConfig":
        """Load modular configuration from TOML file."""
        import tomli

        with open(path, "rb") as f:
            data = tomli.load(f)

        # Handle the modular structure
        config_dict: dict[str, Any] = {}

        # Process all fields
        for key, value in data.items():
            if "." in key and isinstance(value, dict):
                # This is a modular section like [python.bare_except]
                # Convert to underscore format for our model
                field_name = key.replace(".", "_").lower()
                config_dict[field_name] = value
            elif key == "python" and isinstance(value, dict):
                # Handle nested python sections
                for nested_key, nested_value in value.items():
                    if nested_key == "tools":
                        # Handle both list format and dict format
                        if isinstance(nested_value, list):
                            config_dict["python_tools"] = nested_value
                        elif isinstance(nested_value, dict):
                            # Convert dict format to list based on enabled flags
                            tools = []
                            if nested_value.get("ruff_enabled", True):
                                tools.append("ruff")
                            if nested_value.get("black_enabled", True):
                                tools.append("black")
                            if nested_value.get("isort_enabled", True):
                                tools.append("isort")
                            if nested_value.get("mypy_enabled", False):
                                tools.append("mypy")
                            config_dict["python_tools"] = tools
                        else:
                            config_dict["python_tools"] = nested_value
                    else:
                        # Convert python.bare_except -> python_bare_except
                        field_name = f"python_{nested_key}".lower()
                        config_dict[field_name] = nested_value
            elif key == "ruff" and isinstance(value, dict):
                # Handle nested ruff sections
                for rule_key, rule_value in value.items():
                    field_name = f"ruff_{rule_key}".lower()
                    config_dict[field_name] = rule_value
            elif key == "test" and isinstance(value, dict):
                # Handle nested test sections
                for test_key, test_value in value.items():
                    field_name = f"test_{test_key}"
                    config_dict[field_name] = test_value
            elif key == "hooks" and isinstance(value, dict):
                # Handle hooks configuration - create proper hook config objects
                hooks_dict = {}
                for hook_name, hook_config in value.items():
                    if hook_name == "pre":
                        hooks_dict[hook_name] = (
                            PreToolHookConfig(**hook_config) if isinstance(hook_config, dict) else PreToolHookConfig()
                        )
                    elif hook_name == "post":
                        hooks_dict[hook_name] = (
                            PostToolHookConfig(**hook_config) if isinstance(hook_config, dict) else PostToolHookConfig()
                        )
                    elif hook_name == "stop":
                        hooks_dict[hook_name] = (
                            StopHookConfig(**hook_config) if isinstance(hook_config, dict) else StopHookConfig()
                        )
                    elif hook_name == "notification":
                        hooks_dict[hook_name] = (
                            NotificationHookConfig(**hook_config)
                            if isinstance(hook_config, dict)
                            else NotificationHookConfig()
                        )
                    elif hook_name == "subagent_stop":
                        hooks_dict[hook_name] = (
                            SubagentStopHookConfig(**hook_config)
                            if isinstance(hook_config, dict)
                            else SubagentStopHookConfig()
                        )
                config_dict["hooks"] = hooks_dict
            else:
                # Regular top-level fields
                config_dict[key] = value

        # Handle special cases where field is passed as string
        if "python.tools" in data:
            config_dict["python_tools"] = data["python.tools"]
        if "test.relaxed_rules" in data:
            config_dict["test_relaxed_rules"] = data["test.relaxed_rules"]

        return cls(**config_dict)

    def save_to_file(self, path: Path) -> None:
        """Save modular configuration to TOML file."""
        import tomli_w

        # Convert to dict with proper structure
        data = {}

        # Handle simple fields
        for field_name in ["version", "max_errors_to_show", "log_level"]:
            if hasattr(self, field_name):
                data[field_name] = getattr(self, field_name)

        # Handle lists
        for field_name in ["access_control", "repo_rules", "test_patterns", "profiles"]:
            if hasattr(self, field_name):
                value = getattr(self, field_name)
                if value:
                    data[field_name] = [item.model_dump() if hasattr(item, "model_dump") else item for item in value]

        # Handle complex objects
        if self.hooks:
            data["hooks"] = {k: v.model_dump() for k, v in self.hooks.items()}

        if self.llm_analysis:
            data["llm_analysis"] = self.llm_analysis.model_dump()

        if self.log_file:
            data["log_file"] = str(self.log_file)

        # Handle modular check configs
        for attr_name in dir(self):
            if attr_name.startswith(("python_", "ruff_")):
                value = getattr(self, attr_name)
                if isinstance(value, CheckConfigBase):
                    # Convert underscore back to dot notation
                    section_name = attr_name.replace("_", ".")
                    data[section_name] = value.model_dump(exclude_none=True)

        # Handle lists that need special formatting
        if hasattr(self, "python_tools"):
            data["python.tools"] = self.python_tools

        if hasattr(self, "test_relaxed_rules"):
            data["test.relaxed_rules"] = self.test_relaxed_rules

        with open(path, "wb") as f:
            tomli_w.dump(data, f)
