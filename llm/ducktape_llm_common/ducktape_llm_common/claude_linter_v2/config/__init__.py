"""Configuration management for Claude Linter v2."""

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
from .modular_models import CheckConfigBase, ModularClaudeLinterConfig

__all__ = [
    # Loader
    "ConfigLoader",
    # Common Models
    "AccessControlRule",
    "AutofixCategory",
    "HookType",
    "LLMAnalysisConfig",
    "LLMPromptTemplates",
    "PatternBasedRule",
    "PredicateRule",
    "RuleAction",
    "TaskProfile",
    "Violation",
    # Modular Models
    "ModularClaudeLinterConfig",
    "CheckConfigBase",
]
