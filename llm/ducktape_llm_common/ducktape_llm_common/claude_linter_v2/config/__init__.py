"""Configuration management for Claude Linter v2."""

from .loader import ConfigLoader
from .models import (
    AccessControlRule,
    AutofixCategory,
    ClaudeLinterConfig,  # Still export main config
    HookConfig,
    HookType,
    LLMAnalysisConfig,
    PredicateRule,
    RuleAction,
    TaskProfile,
    Violation,
)
from .modular_models import CheckConfigBase, ModularClaudeLinterConfig

__all__ = [
    # Loader
    "ConfigLoader",
    # Common Models (used by both legacy and modular)
    "AccessControlRule",
    "AutofixCategory",
    "ClaudeLinterConfig",
    "HookConfig",
    "HookType",
    "LLMAnalysisConfig",
    "PredicateRule",
    "RuleAction",
    "TaskProfile",
    "Violation",
    # Modular Models
    "ModularClaudeLinterConfig",
    "CheckConfigBase",
    # NOTE: HookRequest, HookResponse, HookDecision, ToolInput are deprecated
    # Use hooks.requests and hooks.claude_responses instead
]
