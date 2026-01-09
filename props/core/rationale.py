"""Rationale type for issue explanations.

This module provides a validated Rationale type used consistently across multiple
contexts for meaningful explanation text (10-5000 characters). Each usage provides
its own Field description for context-specific documentation.

The type itself is generic; context-specific descriptions are added via Pydantic Field.
"""

from typing import Annotated

from pydantic import StringConstraints

Rationale = Annotated[str, StringConstraints(min_length=10, max_length=5000, strip_whitespace=True)]
"""Validated rationale text (10-5000 chars, whitespace stripped).

Uses standard Pydantic constraints for proper JSON Schema export.
"""
