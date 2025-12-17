"""MCP server for submitting improved prompts.

Provides a single tool for the improvement agent to submit its final prompt.
Reads the prompt from the workspace filesystem and stores it internally.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import cast

from fastmcp.exceptions import ToolError
from fastmcp.resources import FunctionResource
from fastmcp.tools import FunctionTool
from pydantic import BaseModel, Field

from adgn.mcp.enhanced import EnhancedFastMCP
from adgn.openai_utils.pydantic_strict_mode import OpenAIStrictModeBaseModel
from adgn.props.ids import SnapshotSlug

logger = logging.getLogger(__name__)

# Resource URI constant
IMPROVEMENT_CONTEXT_RESOURCE_URI = "resource://prompt_submission/improvement_context"


class PromptSubmission(BaseModel):
    """Submitted prompt and metadata from improvement agent."""

    prompt_text: str
    rationale: str
    expected_improvement: str


class ExampleInfo(BaseModel):
    """Information about an example for few-shot prompt improvement.

    Note: scope_hash is always non-null now (even for whole-snapshot examples,
    which have a computed hash from AllFilesScope). The composite PK is
    (snapshot_slug, scope_hash).
    """

    snapshot_slug: SnapshotSlug
    scope_hash: str


class ImprovementContext(BaseModel):
    """Context information for few-shot prompt improvement."""

    examples: list[ExampleInfo]
    current_prompt_sha256: str | None = None


class SubmitPromptInput(OpenAIStrictModeBaseModel):
    """Input for submit_prompt tool."""

    prompt_file: str = Field(
        description="Path to prompt file in /workspace/ (e.g., 'improved-prompt.md'). Use basename only, not full path."
    )
    rationale: str = Field(
        description="Explanation of what you changed and why (2-5 sentences). "
        "Be specific about which failure patterns you addressed."
    )
    expected_improvement: str = Field(
        description="What failure patterns this should fix (e.g., 'better dead code detection', "
        "'improved duplication finding across files'). Be concrete and measurable."
    )


class PromptSubmissionServer(EnhancedFastMCP):
    """MCP server for submitting improved prompts.

    Provides:
    - Tool: submit_prompt(prompt_file, rationale, expected_improvement)
    - Resource: resource://prompt_submission/improvement_context (JSON with example info)

    The agent writes its improved prompt to /workspace/{filename}, then calls the tool
    to submit it. The server reads the file from the host-side workspace directory and
    stores it internally.

    On submission:
    1. Read prompt from workspace_root/{prompt_file}
    2. Validate non-empty
    3. Store internally
    4. Mark as submitted (prevents duplicate submissions)
    5. Return success message

    Example:
        improvement_ctx = ImprovementContext(
            examples=[ExampleInfo(snapshot_slug="...", scope_hash="...")],
            current_prompt_sha256="abc123"
        )

        server = PromptSubmissionServer(
            workspace_root=Path("/tmp/workspace"),
            improvement_context=improvement_ctx
        )

        # ... run agent ...

        submission = server.get_submission()
        if submission:
            logger.info(f"Received prompt: {len(submission.prompt_text)} chars")
    """

    submit_prompt_tool: FunctionTool
    improvement_context_resource: FunctionResource

    def __init__(self, workspace_root: Path, improvement_context: ImprovementContext):
        """Initialize prompt submission server.

        Args:
            workspace_root: Host-side path to workspace (where prompt file will be written)
            improvement_context: Few-shot example information to expose as a resource
        """
        super().__init__("PromptSubmission", instructions="Submit improved prompts for evaluation.")
        self._workspace_root = workspace_root
        self._improvement_context = improvement_context
        self._submission: PromptSubmission | None = None

        # Expose improvement context as a resource
        def get_improvement_context() -> ImprovementContext:
            """Few-shot examples for prompt improvement.

            Contains:
            - examples: List of (snapshot_slug, scope_hash) pairs
            - current_prompt_sha256: SHA256 of baseline prompt being improved (if available)

            Query the database to find associated critiques, grader runs, and execution traces
            for these examples. Use the SQL query examples in your workspace for guidance.
            """
            return self._improvement_context

        self.improvement_context_resource = cast(
            FunctionResource, self.resource(IMPROVEMENT_CONTEXT_RESOURCE_URI)(get_improvement_context)
        )

        def submit_prompt(input: SubmitPromptInput) -> str:
            """Submit improved prompt for evaluation.

            Reads the prompt from /workspace/{prompt_file} and stores it for later evaluation.
            Can only be called once per session.

            Returns success message with character count.
            Raises ToolError if:
            - Already submitted
            - File not found
            - File is empty
            - File is outside workspace
            """
            if self._submission is not None:
                raise ToolError(
                    "Prompt already submitted. You can only submit once per session. "
                    "If you need to revise, update the file and restart the agent."
                )

            # Security: ensure file is within workspace (no path traversal)
            prompt_file = Path(input.prompt_file)
            if prompt_file.is_absolute() or ".." in prompt_file.parts:
                raise ToolError(
                    f"Invalid prompt_file: {input.prompt_file}. Must be a basename in /workspace "
                    "(e.g., 'improved-prompt.md'), not an absolute or relative path."
                )

            # Read from host-side workspace
            file_path = self._workspace_root / prompt_file
            if not file_path.exists():
                raise ToolError(
                    f"Prompt file not found: {prompt_file}. "
                    "Make sure you wrote the file to /workspace/{filename} using docker_exec before submitting."
                )

            try:
                prompt_text = file_path.read_text(encoding="utf-8")
            except Exception as e:
                raise ToolError(f"Failed to read prompt file: {e}")

            if not prompt_text.strip():
                raise ToolError(
                    f"Prompt file is empty: {prompt_file}. Write your improved prompt to the file before submitting."
                )

            # Store submission
            self._submission = PromptSubmission(
                prompt_text=prompt_text, rationale=input.rationale, expected_improvement=input.expected_improvement
            )

            logger.info(
                f"Prompt submitted successfully: {len(prompt_text)} chars, "
                f"rationale={len(input.rationale)} chars, expected_improvement={input.expected_improvement[:50]}"
            )

            return (
                f"Prompt submitted successfully ({len(prompt_text):,} characters). "
                "Your submission has been recorded and will be evaluated. "
                "The agent will terminate shortly."
            )

        self.submit_prompt_tool = self.flat_model()(submit_prompt)

    def get_submission(self) -> PromptSubmission | None:
        """Get submitted prompt if available."""
        return self._submission
