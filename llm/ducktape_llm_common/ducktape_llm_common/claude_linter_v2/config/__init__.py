"""Configuration management for Claude Linter v2."""

from .clean_models import ModularConfig, RuleConfig
from .loader import ConfigLoader
from .models import (
    AccessControlRule,
    AutofixCategory,
    HookType,
    LLMAnalysisConfig,
    LLMPromptTemplates,
    PatternBasedRule,
    PredicateRule,
    RuleAction,
    TaskProfile,
    Violation,
)

__all__ = [
    # Common Models
    "AccessControlRule",
    "AutofixCategory",
    # Loader
    "ConfigLoader",
    "HookType",
    "LLMAnalysisConfig",
    "LLMPromptTemplates",
    # Clean Models
    "ModularConfig",
    "PatternBasedRule",
    "PredicateRule",
    "RuleAction",
    "RuleConfig",
    "TaskProfile",
    "Violation",
]
