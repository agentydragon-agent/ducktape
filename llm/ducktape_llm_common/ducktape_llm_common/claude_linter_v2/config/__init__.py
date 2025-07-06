"""Configuration management for Claude Linter v2."""

from .loader import ConfigLoader
from .models import (
    AccessControlRule,
    AutofixCategory,
    HookConfig,
    HookDecision,
    HookRequest,
    HookResponse,
    HookType,
    LLMAnalysisConfig,
    PredicateRule,
    RuleAction,
    TaskProfile,
    ToolInput,
    Violation,
)
from .modular_models import CheckConfigBase, ModularClaudeLinterConfig

__all__ = [
    # Loader
    "ConfigLoader",
    # Common Models (used by both legacy and modular)
    "AccessControlRule",
    "AutofixCategory",
    "HookConfig",
    "HookDecision",
    "HookRequest",
    "HookResponse",
    "HookType",
    "LLMAnalysisConfig",
    "PredicateRule",
    "RuleAction",
    "TaskProfile",
    "ToolInput",
    "Violation",
    # Modular Models
    "ModularClaudeLinterConfig",
    "CheckConfigBase",
]
