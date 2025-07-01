#!/usr/bin/env python3
"""Claude Code pre-tool-use hook for checking non-autofixable violations.

This hook runs before Claude writes Python files, blocking if there are
violations that cannot be automatically fixed.
"""

import json
import logging
import subprocess
import sys
from pathlib import Path

# Set up logging - only to file, not stderr (which is used for hook output)
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("/tmp/claude-pre-hook.log")],
)
logger = logging.getLogger(__name__)


def main():
    """Main pre-write hook entry point."""
    logger.debug("Pre-hook invoked")

    # Read JSON input from stdin
    try:
        input_data = json.load(sys.stdin)
        logger.debug(f"Input data: {json.dumps(input_data, indent=2)}")
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing JSON input: {e}")
        print(f"Error parsing JSON input: {e}", file=sys.stderr)
        sys.exit(1)

    # Extract tool name and parameters
    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})

    # Only process Write tool
    if tool_name != "Write":
        logger.debug(f"Skipping non-Write tool: {tool_name}")
        sys.exit(0)

    # Check if it's a Python file
    file_path = tool_input.get("file_path", "")
    if not file_path.endswith(".py"):
        logger.debug(f"Skipping non-Python file: {file_path}")
        sys.exit(0)

    # Get the content to be written
    content = tool_input.get("content", "")
    if not content:
        logger.debug("No content to check")
        sys.exit(0)

    logger.info(f"Checking Python file: {file_path}")

    # Write content to a temporary file for checking
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        # Get the enabled rules from claude config
        from ducktape_llm_common.linters.claude_config import ClaudeLinterConfig

        config = ClaudeLinterConfig.find_config()
        enabled_rules = ",".join(config.rules.enabled_rules)

        # Run ruff check to find all violations
        logger.debug(f"Running ruff check with rules: {enabled_rules}")
        result = subprocess.run(
            ["ruff", "check", "--select", enabled_rules, "--output-format", "json", tmp_path],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            # No violations
            logger.info("No violations found")
            return

        # Parse violations
        try:
            violations = json.loads(result.stdout)
            logger.info(f"Found {len(violations)} total violations")
        except json.JSONDecodeError:
            # Couldn't parse ruff output
            logger.warning(f"Could not parse ruff output: {result.stdout}")
            return

        # Check which violations are NOT auto-fixable
        # First, make a copy of the file to test fixes on
        import shutil

        tmp_copy = tmp_path + ".copy"
        shutil.copy2(tmp_path, tmp_copy)

        try:
            # Run ruff with --fix to see what can be fixed
            fix_result = subprocess.run(
                ["ruff", "check", "--select", enabled_rules, "--fix", "--output-format", "json", tmp_copy],
                capture_output=True,
                text=True,
            )

            # If fix_result still has violations, those are NOT fixable
            unfixable_violations = []
            if fix_result.returncode != 0 and fix_result.stdout:
                try:
                    unfixable = json.loads(fix_result.stdout)
                    unfixable_violations = unfixable
                    logger.info(f"Found {len(unfixable_violations)} non-fixable violations")
                except json.JSONDecodeError:
                    # If we can't determine, assume all are unfixable
                    logger.warning("Could not parse fix result, assuming all violations are unfixable")
                    unfixable_violations = violations
        finally:
            # Clean up the copy
            Path(tmp_copy).unlink(missing_ok=True)

        if unfixable_violations:
            logger.error(f"Blocking write due to {len(unfixable_violations)} non-fixable violations")

            # Format error message for Claude
            print("=" * 60, file=sys.stderr)
            print("🚨 NON-FIXABLE VIOLATIONS DETECTED", file=sys.stderr)
            print("=" * 60, file=sys.stderr)
            print(f"\nFile: {file_path}", file=sys.stderr)
            print("\nThe following violations cannot be auto-fixed:", file=sys.stderr)

            for v in unfixable_violations:
                loc = v.get("location", {})
                print(
                    f"  Line {loc.get('row', 0)}:{loc.get('column', 0)} - {v.get('code', '')} {v.get('message', '')}",
                    file=sys.stderr,
                )

            print("\nPlease fix these issues before writing the file.", file=sys.stderr)

            # Exit code 2 to block with continue: true
            sys.exit(2)

    finally:
        # Clean up temp file
        Path(tmp_path).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
