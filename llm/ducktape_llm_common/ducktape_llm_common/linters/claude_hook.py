#!/usr/bin/env python3
"""Claude Code post-tool-use hook for linting edited files.

This hook runs after Claude uses Write, Edit, or MultiEdit tools to modify files,
ensuring code quality standards are maintained.
"""

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from ducktape_llm_common.linters.claude_rules import ClaudeRulesLinter

# Set up logging - only to file, not stderr (which is used for hook output)
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("/tmp/claude-linter-hook.log")],
)
logger = logging.getLogger(__name__)


def main():
    """Main hook entry point for Claude Code post-tool-use linting."""
    # Set up logging
    log_file = Path("/tmp/claude-linter-hook.log")
    with open(log_file, "a") as f:
        f.write(f"\n=== Hook invoked at {datetime.now().isoformat()} ===\n")
        f.write(f"Working directory: {os.getcwd()}\n")

    # Read JSON input from stdin
    try:
        input_data = json.load(sys.stdin)
        with open(log_file, "a") as f:
            f.write(f"Input data: {json.dumps(input_data, indent=2)}\n")
    except json.JSONDecodeError as e:
        with open(log_file, "a") as f:
            f.write(f"Error parsing JSON: {e}\n")
        print(f"Error parsing JSON input: {e}", file=sys.stderr)
        sys.exit(1)

    # Extract tool name and parameters
    tool_name = input_data.get("tool_name", "")
    tool_params = input_data.get("tool_input", {})

    # Only process Write tool - for new files, all violations are from this tool call
    if tool_name != "Write":
        with open(log_file, "a") as f:
            f.write(f"Skipping - tool name '{tool_name}' is not Write\n")
        sys.exit(0)

    # Collect files to lint
    files_to_lint = set()

    # For Write tool, get the file path
    file_path = tool_params.get("file_path")
    if file_path and file_path.endswith(".py"):
        files_to_lint.add(Path(file_path))

    if not files_to_lint:
        # No Python files edited
        with open(log_file, "a") as f:
            f.write("No Python files to lint\n")
        sys.exit(0)

    with open(log_file, "a") as f:
        f.write(f"Files to lint: {[str(f) for f in files_to_lint]}\n")

    # Create linter instance with treat_all_as_errors=True for Write operations
    try:
        linter = ClaudeRulesLinter(treat_all_as_errors=True)
        with open(log_file, "a") as f:
            f.write("Linter instance created with treat_all_as_errors=True\n")
    except Exception as e:
        with open(log_file, "a") as f:
            f.write(f"Error creating linter: {e}\n")
        sys.exit(1)

    # Collect results
    all_results = []

    for file_path in files_to_lint:
        if not file_path.exists():
            with open(log_file, "a") as f:
                f.write(f"File does not exist: {file_path}\n")
            continue

        with open(log_file, "a") as f:
            f.write(f"Checking file: {file_path}\n")

        # Force the file to be checked by clearing its last check time
        file_key = str(file_path)
        if file_key in linter._state:
            linter._state[file_key]["last_check"] = 0
            with open(log_file, "a") as f:
                f.write(f"Cleared last check time for {file_key}\n")

        # Run linter on the specific file
        try:
            result = linter.lint_file(file_path)
            with open(log_file, "a") as f:
                f.write(
                    f"Lint result: has_errors={result.has_errors}, "
                    f"errors={len(result.errors)}, warnings={len(result.warnings)}\n",
                )
        except Exception as e:
            with open(log_file, "a") as f:
                f.write(f"Error linting file: {e}\n")
            continue

        if result.has_errors:
            all_results.append(result)
            with open(log_file, "a") as f:
                f.write(f"Added to results - total errors now: {len(all_results)}\n")

    if all_results:
        # Format and display violations to stderr
        # We need to redirect click's output to stderr for the hook to work properly
        import contextlib
        import io

        # Capture the formatted output
        output_buffer = io.StringIO()
        with contextlib.redirect_stdout(output_buffer):
            linter.format_violations(all_results)

        # Send to stderr
        print(output_buffer.getvalue(), file=sys.stderr)

        # Exit code 2 blocks execution and sends errors back to Claude
        sys.exit(2)

    # Success - could output a message to stdout if desired
    print(f"✅ Linter passed for {len(files_to_lint)} Python file(s)")
    sys.exit(0)


if __name__ == "__main__":
    main()
