"""Ducktape LLM Common - Shared utilities, linters, and prompts for LLM development workflows.

This package provides:
- Common linters for work tracking and metadata validation
- Prompts and instructions for AI agents
- Version management utilities for metadata structure
- Pre-commit integration support
- Quick-start templates for common scenarios
"""

# Package metadata
__version__ = "0.1.0"
__author__ = "Ducktape Development Team"
__email__ = "dev@ducktape.ai"

# Metadata version constant - defines the current metadata structure version
METADATA_VERSION = 1

# Re-export commonly used items for convenience
from ducktape_llm_common.utils import (
    get_metadata_version,
    validate_metadata_version,
)

__all__ = [
    "__version__",
    "METADATA_VERSION",
    "get_metadata_version",
    "validate_metadata_version",
]
