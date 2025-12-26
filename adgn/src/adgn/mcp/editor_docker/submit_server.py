from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Literal

from fastmcp.exceptions import ToolError
from fastmcp.tools import FunctionTool

from mcp_infra.enhanced import EnhancedFastMCP
from openai_utils.pydantic_strict_mode import OpenAIStrictModeBaseModel

logger = logging.getLogger(__name__)

EDIT_RESOURCE_URI = "resource://edit/target"


class SubmitSuccessInput(OpenAIStrictModeBaseModel):
    message: str
    content: str


class SubmitFailureInput(OpenAIStrictModeBaseModel):
    message: str


@dataclass(frozen=True)
class SubmitStatePending:
    """No submission made yet."""

    kind: Literal["pending"] = "pending"


@dataclass(frozen=True)
class SubmitStateSuccess:
    """Success submission with edited content."""

    kind: Literal["success"] = "success"
    content: str = ""


@dataclass(frozen=True)
class SubmitStateFailure:
    """Failure submission with message."""

    kind: Literal["failure"] = "failure"
    message: str = ""


SubmitState = SubmitStatePending | SubmitStateSuccess | SubmitStateFailure


class EditorSubmitServer(EnhancedFastMCP):
    """Host-side MCP server for the docker-editor flow.

    Exposes a resource with the original file content and tools to declare
    success/failure with an optional message and, on success, the final file content.
    """

    submit_success_tool: FunctionTool
    submit_failure_tool: FunctionTool

    def __init__(self, *, original_content: str, filename: str):
        super().__init__("Editor Submit Server", instructions="Submit edited file or failure message")
        self._original_content = original_content
        self._filename = filename
        self._state: SubmitState = SubmitStatePending()

        @self.resource(EDIT_RESOURCE_URI, name=filename, title="Original file", mime_type="text/plain")
        def edit_resource() -> str:
            return self._original_content

        self.edit_resource = edit_resource

        def submit_success(input: SubmitSuccessInput) -> None:
            if not isinstance(self._state, SubmitStatePending):
                raise ToolError("submit already called")
            self._state = SubmitStateSuccess(content=input.content)

        def submit_failure(input: SubmitFailureInput) -> None:
            if not isinstance(self._state, SubmitStatePending):
                raise ToolError("submit already called")
            self._state = SubmitStateFailure(message=input.message)

        self.submit_success_tool = self.flat_model()(submit_success)
        self.submit_failure_tool = self.flat_model()(submit_failure)

    @property
    def state(self) -> SubmitState:
        return self._state
