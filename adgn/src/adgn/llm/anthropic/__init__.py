"""Stronger-typed Pydantic wrappers for Anthropic SDK types.

Parallel to adgn.llm.openai for OpenAI types.

Anthropic SDK uses TypedDicts (runtime dicts with type hints only).
This package provides Pydantic BaseModels for runtime validation and proper attribute access.
"""
