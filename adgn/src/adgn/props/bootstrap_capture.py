"""Bootstrap capture utilities for inspecting agent initial context.

This module provides tools to capture and display what an agent sees at startup,
without actually running the LLM. Useful for debugging bootstrap, checking for
duplication in prompts, and verifying MCP tool availability.

Usage:
    client = CapturingClient()
    try:
        await run_critic(..., client=client)
    except BootstrapCaptured:
        print(format_bootstrap_output(client.captured))
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, NoReturn

from adgn.openai_utils.model import OpenAIModelProto

if TYPE_CHECKING:
    from adgn.openai_utils.model import ResponsesRequest


class BootstrapCaptured(Exception):  # noqa: N818 - not an error, a control flow signal
    """Raised to signal bootstrap capture completed.

    This is not an error condition - it's a deliberate signal to capture
    the first API request without actually calling the LLM.
    """


class CapturingClient(OpenAIModelProto):
    """Mock OpenAI client that captures the first API request then aborts.

    Implements OpenAIModelProto to satisfy type requirements. When
    responses_create() is called, it captures the request and raises
    BootstrapCaptured to abort the agent loop.

    Attributes:
        captured: The captured ResponsesRequest, or None if not yet captured.
        model: Placeholder model name for protocol compliance.
    """

    model: str = "bootstrap-capture-placeholder"

    def __init__(self) -> None:
        self.captured: ResponsesRequest | None = None

    async def responses_create(self, req: ResponsesRequest) -> NoReturn:
        """Capture the request and signal completion.

        Args:
            req: The API request that would be sent to OpenAI.

        Raises:
            BootstrapCaptured: Always raised after capturing the request.
        """
        self.captured = req
        raise BootstrapCaptured("Bootstrap captured")


def format_bootstrap_output(req: ResponsesRequest) -> str:
    """Format captured request for human-readable display.

    Args:
        req: The captured ResponsesRequest.

    Returns:
        JSON-formatted string showing the request contents.

    Raises:
        ValueError: If req is None.
    """
    if req is None:
        raise ValueError("No request captured (agent may have exited before first API call)")

    # Convert to dict for JSON serialization
    # Use model_dump with mode="json" for JSON-compatible output
    data = req.model_dump(mode="json")

    return json.dumps(data, indent=2, ensure_ascii=False)
