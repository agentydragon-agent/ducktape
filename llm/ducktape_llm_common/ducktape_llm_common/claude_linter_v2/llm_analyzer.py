"""LLM-powered code analysis for Claude Linter v2."""

import json
import logging
from typing import Any

from .config.models import LLMAnalysisConfig, Violation

logger = logging.getLogger(__name__)


class LLMAnalyzer:
    """Analyzes code using LLM for advanced checks."""

    def __init__(self, config: LLMAnalysisConfig) -> None:
        """Initialize with LLM analysis configuration."""
        self.config = config
        self._cost_tracker = 0.0  # Track cost within session

    def analyze_code(
        self,
        file_path: str,
        content: str,
        tool_name: str,
        tool_input: dict[str, Any] | None = None,
        context_lines: int = 50,
    ) -> tuple[bool, str | None, list[Violation]]:
        """Analyze code using LLM.

        Args:
            file_path: Path to the file being analyzed
            content: Full file content or patch
            tool_name: Name of the tool (Write, Edit, MultiEdit)
            tool_input: Tool input for context (e.g., old_string, new_string)
            context_lines: Number of context lines for patches

        Returns:
            Tuple of (is_ok, llm_message, violations)
        """
        if not self.config.enabled:
            return True, None, []

        # Check cost limit
        if self._cost_tracker >= self.config.daily_cost_limit:
            logger.warning(f"LLM analysis cost limit reached: ${self._cost_tracker}")
            return True, None, []

        try:
            # Build the analysis prompt based on tool type
            if tool_name == "Write":
                prompt = self.config.prompts.full_file_analysis.format(file_path=file_path, content=content)
            elif tool_name in ("Edit", "MultiEdit"):
                prompt = self._build_patch_prompt(file_path, content, tool_input, context_lines)
            else:
                # Unknown tool, skip LLM analysis
                return True, None, []

            # Call LLM (this would use the actual API)
            result = self._call_llm(prompt)

            # Parse result
            is_ok, message, violations = self._parse_llm_result(result, file_path)

            return is_ok, message, violations

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error(f"LLM analysis failed: {e}")
            # On error, don't block the operation
            return True, None, []

    def _build_patch_prompt(
        self, file_path: str, full_content: str, tool_input: dict[str, Any] | None, context_lines: int
    ) -> str:
        """Build prompt for analyzing a patch/edit."""
        if not tool_input:
            # Fallback to full file analysis
            return self.config.prompts.full_file_analysis.format(file_path=file_path, content=full_content)

        # For Edit tool
        if "old_string" in tool_input and "new_string" in tool_input:
            old_string = tool_input["old_string"]
            new_string = tool_input["new_string"]

            # Find the location of the edit in the file
            lines = full_content.split("\n")
            edit_line = None
            for i, line in enumerate(lines):
                if old_string in line:
                    edit_line = i
                    break

            if edit_line is not None:
                # Get context around the edit
                start = max(0, edit_line - context_lines)
                end = min(len(lines), edit_line + context_lines)
                context = "\n".join(lines[start:end])
            else:
                context = full_content[:1000]  # First 1000 chars as fallback

            return self.config.prompts.edit_analysis.format(
                file_path=file_path, old_string=old_string, new_string=new_string, context=context
            )

        # For MultiEdit tool
        if "edits" in tool_input:
            edits = tool_input["edits"]
            edits_summary = "\n\n".join(
                [
                    f"Edit {i + 1}:\nFrom: {e.get('old_string', '')[:100]}...\nTo: {e.get('new_string', '')[:100]}..."
                    for i, e in enumerate(edits[:5])  # Limit to first 5 edits
                ]
            )

            return self.config.prompts.multi_edit_analysis.format(file_path=file_path, edits_summary=edits_summary)

        # Fallback
        return self.config.prompts.full_file_analysis.format(file_path=file_path, content=full_content)

    def _call_llm(self, prompt: str) -> dict[str, Any]:
        """Call the LLM API and return the result.

        This is a placeholder - actual implementation would use OpenAI/Anthropic API.
        """
        # TODO: Implement actual LLM API call
        # For now, return a mock response
        logger.info(f"Would call LLM with model {self.config.model}")

        # Estimate cost (rough approximation)
        prompt_tokens = len(prompt) / 4  # Rough token estimate
        self._cost_tracker += prompt_tokens * 0.000001  # Mock cost

        # Mock response - always return OK for now
        return {"ok": True, "violations": []}

    def _parse_llm_result(self, result: dict[str, Any], file_path: str) -> tuple[bool, str | None, list[Violation]]:
        """Parse LLM result into our format."""
        try:
            is_ok = result.get("ok", True)
            message = result.get("message")

            violations = []
            for v in result.get("violations", []):
                violations.append(
                    Violation(
                        rule=v.get("rule", "LLM:unknown"),
                        line=v.get("line", 1),
                        column=v.get("column", 0),
                        message=v.get("message", "LLM detected issue"),
                        fixable=False,  # LLM issues are not auto-fixable
                    )
                )

            return is_ok, message, violations

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error(f"Failed to parse LLM result: {e}")
            return True, None, []
