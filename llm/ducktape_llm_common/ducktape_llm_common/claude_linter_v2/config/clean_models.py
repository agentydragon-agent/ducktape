"""Clean configuration models with no dict manipulation or dynamic fields."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

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


class RuleConfig(BaseModel):
    """Configuration for a single rule."""

    enabled: bool = Field(True, description="Whether this rule is enabled")
    blocks_pre_hook: bool | None = Field(None, description="Override default pre-hook blocking (None = use default)")
    blocks_stop_hook: bool | None = Field(None, description="Override default stop-hook blocking (None = use default)")
    message: str | None = Field(None, description="Override default error message")


class ModularConfig(BaseModel):
    """Clean modular configuration with strict validation."""

    model_config = {"extra": "forbid"}  # No dynamic fields allowed

    # Core settings
    version: Literal["2.0"] = Field("2.0", description="Config version")
    max_errors_to_show: int = Field(3, description="Maximum errors to display in hook responses")

    # Rules configuration - single dict for all rules
    rules: dict[str, RuleConfig] = Field(
        default_factory=dict,
        description="Rule configurations keyed by canonical name (e.g., 'python.bare_except', 'ruff.E722')",
    )

    # Access control
    access_control: list[AccessControlRule] = Field(default_factory=list, description="Path-based access control rules")

    # Repo-wide predicate rules
    repo_rules: list[PredicateRule] = Field(default_factory=list, description="Repository-wide predicate rules")

    # Python tools
    python_tools: list[str] = Field(default_factory=lambda: ["ruff", "mypy"], description="Python linting tools to use")

    # Hook configurations
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

    # Pattern-based file rules
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

    @classmethod
    def from_toml(cls, path: Path) -> "ModularConfig":
        """Load configuration from TOML file - let Pydantic handle parsing."""
        import tomli

        with open(path, "rb") as f:
            data = tomli.load(f)

        # Transform flat dotted keys to nested structure for rules
        if "rules" not in data:
            data["rules"] = {}

        # Handle dotted keys like [rules."python.bare_except"]
        keys_to_remove = []
        for key, value in data.items():
            if key.startswith("rules."):
                rule_key = key[6:]  # Remove "rules." prefix
                # Remove quotes if present
                if rule_key.startswith('"') and rule_key.endswith('"'):
                    rule_key = rule_key[1:-1]
                data["rules"][rule_key] = value
                keys_to_remove.append(key)

        # Remove the flat keys we've processed
        for key in keys_to_remove:
            del data[key]

        # Let Pydantic validate and create the model
        return cls(**data)

    def get_rule_config(self, rule_key: str) -> RuleConfig | None:
        """Get configuration for a specific rule."""
        # First check explicit config
        if rule_key in self.rules:
            return self.rules[rule_key]

        # Fall back to defaults from registry
        from ..rule_registry import RuleRegistry

        rule_def = RuleRegistry.get_by_key(rule_key)
        if rule_def:
            # Create a RuleConfig from registry defaults
            return RuleConfig(
                enabled=True,  # Rules in registry are enabled by default
                blocks_pre_hook=rule_def.default_blocks_pre,
                blocks_stop_hook=rule_def.default_blocks_stop,
                message=rule_def.default_message,
            )

        return None

    def get_ruff_codes_to_select(self) -> list[str]:
        """Get list of ruff codes to force enable."""
        from ..rule_registry import RuleRegistry

        codes = []

        # First, get all ruff rules from the registry that are enabled by default
        for rule_def in RuleRegistry.get_all_rules():
            if rule_def.category == "ruff":
                key = f"ruff.{rule_def.code}"
                # Check if there's an explicit config for this rule
                if key in self.rules:
                    # Use explicit config
                    rule_config = self.rules[key]
                    # Handle both dict and RuleConfig objects
                    if isinstance(rule_config, dict):
                        if rule_config.get("enabled", True):
                            codes.append(rule_def.code)
                    elif rule_config.enabled:
                        codes.append(rule_def.code)
                else:
                    # Use default from registry
                    if rule_def.default_blocks_pre or rule_def.default_blocks_stop:
                        codes.append(rule_def.code)

        return codes
