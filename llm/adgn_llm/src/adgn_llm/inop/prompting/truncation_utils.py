"""Unified truncation utilities for the Claude instruction optimizer."""

import json
from pathlib import Path
from typing import cast

import tiktoken
from openai.types.responses.response import Response
from openai.types.responses.response_output_message import ResponseOutputMessage
from openai.types.responses.response_output_text import ResponseOutputText

from adgn_llm.inop.config import OptimizerConfig
from adgn_llm.inop.engine.models import FileInfo


class TruncationManager:
    """Unified truncation management for files, content, and messages."""

    def __init__(self, config: OptimizerConfig):
        self.config = config
        self._encoding = tiktoken.encoding_for_model(config.grader.model)

    def count_tokens(self, text: str) -> int:
        """Count tokens in text using the configured model encoding."""
        return len(self._encoding.encode(text))

    def truncate_text(self, text: str, max_length: int, suffix: str = "...") -> str:
        """Truncate text to max_length with optional suffix."""
        if len(text) <= max_length:
            return text
        return text[: max_length - len(suffix)] + suffix

    def _truncated_content(self, content: str, max_chars: int) -> str:
        """Helper to create truncated content with standard message."""
        if len(content) <= max_chars:
            return content
        return content[:max_chars] + f"\n... [TRUNCATED: {len(content)} chars total, showing first {max_chars}]"

    def _skipped_content(self, content: str, threshold: int) -> str:
        """Helper to create skipped content message."""
        return f"[SKIPPED: File too large ({len(content)} chars > {threshold} limit)]"

    def truncate_file_content_by_size(
        self,
        files: list[dict[str, str]],
        max_size: int,
    ) -> dict[str, str]:
        """Truncate file contents by character size.

        Args:
            files: List of file dicts with 'path' and 'content' keys
            max_size: Maximum characters per file

        Returns:
            Dict mapping file paths to truncated content
        """
        truncated = {}
        skip_threshold = max_size * 5  # Skip extremely large files

        for file_info in files:
            path = file_info["path"]
            content = file_info["content"]

            if len(content) > skip_threshold:
                truncated[path] = self._skipped_content(content, skip_threshold)
            else:
                truncated[path] = self._truncated_content(content, max_size)

        return truncated

    def truncate_files_by_tokens(
        self,
        files_info: list[dict[str, str]] | list[FileInfo],
        max_tokens: int,
    ) -> list[dict[str, str]] | list[FileInfo]:
        """Truncate files to fit within token budget using binary search.

        Args:
            files_info: List of file dicts with 'path' and 'content' keys OR FileInfo objects
            max_tokens: Maximum tokens for all files combined

        Returns:
            Truncated files_info that fits within token budget (same element type as input)
        """

        def count_files_tokens(files: list[dict[str, str]] | list[FileInfo]) -> int:
            if files and isinstance(files[0], FileInfo):
                files_json = json.dumps([fi.model_dump() for fi in cast(list[FileInfo], files)], indent=2)
            else:
                files_json = json.dumps(files, indent=2)
            return self.count_tokens(files_json)

        current_tokens = count_files_tokens(files_info)
        if current_tokens <= max_tokens:
            return files_info

        # Build a normalized list [(path, content, original_obj)] so we can sort safely
        normalized: list[tuple[str, str, dict[str, str] | FileInfo]] = []
        if files_info and isinstance(files_info[0], FileInfo):
            for fi in files_info:  # type: ignore[assignment]
                assert isinstance(fi, FileInfo)
                normalized.append((fi.path, fi.content, fi))
        else:
            for d in files_info:  # type: ignore[assignment]
                assert isinstance(d, dict)
                normalized.append((d["path"], d["content"], d))

        # Sort by content length desc so we try to fit smaller ones later
        normalized.sort(key=lambda t: len(t[1]), reverse=True)

        truncated_files_dicts: list[dict[str, str]] = []
        truncated_files_models: list[FileInfo] = []
        remaining_budget = max_tokens

        for path, content, original in normalized:
            # Calculate tokens for this file in JSON format
            single_file_json = json.dumps(
                [{"path": path, "content": content}],
                indent=2,
            )
            file_tokens = self.count_tokens(single_file_json)

            if file_tokens <= remaining_budget:
                # File fits, include original object as-is
                if isinstance(original, FileInfo):
                    truncated_files_models.append(original)
                else:
                    truncated_files_dicts.append(original)
                remaining_budget -= file_tokens
                continue

            # File doesn't fit; attempt truncated version if we have reasonable space
            if remaining_budget <= 1000:
                break

            # Binary search to find max content that fits
            max_chars = len(content)
            min_chars = 0
            while min_chars < max_chars:
                mid_chars = (min_chars + max_chars + 1) // 2
                truncated_content = self._truncated_content(content, mid_chars)
                test_file_json = json.dumps(
                    [{"path": path, "content": truncated_content}],
                    indent=2,
                )
                test_tokens = self.count_tokens(test_file_json)
                if test_tokens <= remaining_budget:
                    min_chars = mid_chars
                else:
                    max_chars = mid_chars - 1

            if min_chars > 0:
                final_content = self._truncated_content(content, min_chars)
                if isinstance(original, FileInfo):
                    truncated_files_models.append(FileInfo(path=path, content=final_content))
                else:
                    truncated_files_dicts.append({"path": path, "content": final_content})
                final_file_json = json.dumps(
                    [{"path": path, "content": final_content}],
                    indent=2,
                )
                remaining_budget -= self.count_tokens(final_file_json)
            # Continue loop; we may still try smaller files

        # Compose result preserving input element type
        result: list[dict[str, str]] | list[FileInfo]
        if files_info and isinstance(files_info[0], FileInfo):
            result = truncated_files_models
        else:
            result = truncated_files_dicts

        final_tokens = count_files_tokens(result)
        assert final_tokens <= max_tokens, f"File truncation failed: {final_tokens} tokens > {max_tokens} limit"
        return result

    def truncate_file_by_bytes(
        self,
        file_path: Path,
        max_bytes: int,
    ) -> str:
        """Read and truncate a single file by byte size.

        Args:
            file_path: Path to the file
            max_bytes: Maximum bytes to read

        Returns:
            File content, possibly truncated
        """
        try:
            file_size = file_path.stat().st_size

            if file_size > max_bytes:
                with file_path.open("r", encoding="utf-8") as f:
                    content = f.read(max_bytes)
                return self._truncated_content(
                    content,
                    len(content),
                )  # Will show the truncation message
            return file_path.read_text()
        except UnicodeDecodeError:
            return "<<not a plaintext file>>"


def extract_text_from_openai_response(response: Response) -> str:
    """Extract text content from OpenAI response, handling nested message structure.

    Args:
        response: OpenAI response object

    Returns:
        First text content found in the response

    Raises:
        RuntimeError: If no text content is found
    """
    for item in response.output:
        if isinstance(item, ResponseOutputMessage) and item.type == "message":
            for content_item in item.content:
                if isinstance(content_item, ResponseOutputText):
                    return content_item.text

    raise RuntimeError("No text content found in OpenAI response")
