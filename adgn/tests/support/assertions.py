"""Assertion helpers for test validation - verify tool calls and extract outputs."""

from __future__ import annotations

from collections.abc import Sequence
import json
import logging
from typing import TypeGuard

from pydantic import BaseModel
import pytest

from adgn.openai_utils.model import FunctionCallItem, ResponsesRequest, UserMessage
from tests.support.extraction import get_last_function_output

logger = logging.getLogger(__name__)


def assert_last_call(req: ResponsesRequest, expected_tool: str):
    """Assert last FunctionCallItem matches expected tool."""
    if isinstance(req.input, str):
        logger.error("Full request dump:")
        logger.error(json.dumps(req.model_dump(mode="json"), indent=2))
        pytest.fail(f"Expected FunctionCallItem for '{expected_tool}', got string input. See log for full request.")

    # Find last FunctionCallItem
    for item in reversed(req.input):
        if isinstance(item, FunctionCallItem):
            actual_name = item.name
            if expected_tool in actual_name:
                return  # Success

            logger.error("Full request dump:")
            logger.error(json.dumps(req.model_dump(mode="json"), indent=2))
            pytest.fail(f"Expected last call to be '{expected_tool}', got '{actual_name}'. See log for full request.")

    logger.error("Full request dump:")
    logger.error(json.dumps(req.model_dump(mode="json"), indent=2))
    pytest.fail(f"No FunctionCallItem found. Expected '{expected_tool}'. See log for full request.")


def extract_output[T: BaseModel](req: ResponsesRequest, output_type: type[T]) -> T:
    """Extract and validate output from last FunctionCallOutputItem."""
    try:
        return get_last_function_output(req, output_type)
    except Exception as e:
        logger.error("Full request dump:")
        logger.error(json.dumps(req.model_dump(mode="json"), indent=2))
        pytest.fail(f"Failed to extract {output_type.__name__}: {e}. See log for full request.")
        raise AssertionError("unreachable")


def assert_and_extract[T: BaseModel](req: ResponsesRequest, expected_tool: str, output_type: type[T]) -> T:
    """Assert expected tool and extract its output."""
    assert_last_call(req, expected_tool)
    return extract_output(req, output_type)


# Type narrowing helpers (TypeGuard)


def is_all_function_calls(items: Sequence[UserMessage | FunctionCallItem]) -> TypeGuard[Sequence[FunctionCallItem]]:
    """TypeGuard to narrow Sequence[UserMessage | FunctionCallItem] to Sequence[FunctionCallItem]."""
    return all(isinstance(x, FunctionCallItem) for x in items)


def is_all_user_messages(items: Sequence[UserMessage | FunctionCallItem]) -> TypeGuard[Sequence[UserMessage]]:
    """TypeGuard to narrow Sequence[UserMessage | FunctionCallItem] to Sequence[UserMessage]."""
    return all(isinstance(x, UserMessage) for x in items)
