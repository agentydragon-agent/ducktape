#!/usr/bin/env python3
"""Claude Code post-tool-use hook for auto-fixing violations.

This hook runs after Claude writes Python files, automatically fixing
what it can and informing Claude of the changes.
"""

import json
import logging
import subprocess
import sys
from pathlib import Path

from ducktape_llm_common.linters.text_fixes import fix_all_text_issues

# Set up logging - only to file, not stderr (which is used for hook output)
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("/tmp/claude-post-hook.log")],
)
logger = logging.getLogger(__name__)


def main():
    """Main post-write hook entry point."""
    logger.debug("Post-hook invoked")

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

    # Only process Write, Edit, and MultiEdit tools
    if tool_name not in ["Write", "Edit", "MultiEdit"]:
        logger.debug(f"Skipping non-file-editing tool: {tool_name}")
        sys.exit(0)

    # Get the file path
    file_path = tool_input.get("file_path", "")

    file_path = Path(file_path)
    if not file_path.exists():
        logger.warning(f"File does not exist: {file_path}")
        sys.exit(0)

    logger.info(f"Processing file: {file_path}")

    # Track what was fixed
    fixed_items = []

    # Run text fixes first (for all file types)
    logger.debug("Running text fixes")
    text_fixes = fix_all_text_issues(file_path)
    if text_fixes:
        fixed_items.extend(text_fixes)
        logger.info(f"Fixed text issues: {text_fixes}")

    # For Python files, also run ruff
    if file_path.suffix == ".py":
        logger.debug("Processing Python-specific fixes")

        # Get the enabled rules from claude config
        from ducktape_llm_common.linters.claude_config import ClaudeLinterConfig

        config = ClaudeLinterConfig.find_config()
        enabled_rules = ",".join(config.rules.enabled_rules)

        # Run ruff format first (replaces black)
        logger.debug("Running ruff format")
        format_result = subprocess.run(["ruff", "format", str(file_path)], capture_output=True, text=True)
        logger.debug(f"Format result: {format_result.returncode}, stdout: {format_result.stdout}")

        # Check what violations exist
        logger.debug(f"Checking violations with rules: {enabled_rules}")
        check_result = subprocess.run(
            ["ruff", "check", "--select", enabled_rules, "--output-format", "json", str(file_path)],
            capture_output=True,
            text=True,
        )

        # Count violations before fix
        violations_before = []
        if check_result.returncode != 0 and check_result.stdout:
            try:
                violations_before = json.loads(check_result.stdout)
                logger.info(f"Found {len(violations_before)} violations before fix")
            except json.JSONDecodeError:
                logger.warning("Could not parse check result")
                violations_before = []

        # Run ruff fix for auto-fixable violations
        logger.debug("Running ruff fix")
        subprocess.run(
            ["ruff", "check", "--select", enabled_rules, "--fix", str(file_path)],
            capture_output=True,
            text=True,
        )

        # Check what violations remain after fixing
        logger.debug("Checking violations after fix")
        check_after = subprocess.run(
            ["ruff", "check", "--select", enabled_rules, "--output-format", "json", str(file_path)],
            capture_output=True,
            text=True,
        )

        violations_after = []
        if check_after.returncode != 0 and check_after.stdout:
            try:
                violations_after = json.loads(check_after.stdout)
                logger.info(f"Found {len(violations_after)} violations after fix")
            except json.JSONDecodeError:
                logger.warning("Could not parse check result after fix")
                violations_after = []

        # Calculate what was fixed
        fixed_count = len(violations_before) - len(violations_after)
        # Check if formatting changed the file
        formatted = format_result.returncode == 0 and "reformatted" in format_result.stdout

        logger.info(f"Fixed {fixed_count} violations, formatted: {formatted}")

        if fixed_count > 0:
            # Group fixed violations by type
            fixed_codes = {}
            for v_before in violations_before:
                code = v_before.get("code", "unknown")
                # Check if this violation is gone after fix
                still_exists = any(
                    v_after.get("code") == code and v_after.get("location") == v_before.get("location")
                    for v_after in violations_after
                )
                if not still_exists:
                    fixed_codes[code] = fixed_codes.get(code, 0) + 1

            for code, count in sorted(fixed_codes.items()):
                fixed_items.append(f"{code} ({count}x)")

        if formatted:
            fixed_items.append("code formatting")

    # Report all fixes if any were made
    if fixed_items:
        logger.info(f"Reporting fixes to Claude: {fixed_items}")
        print(f"✅ Auto-fixed in {file_path.name}:", file=sys.stderr)
        for item in fixed_items:
            print(f"  - {item}", file=sys.stderr)
        print("\n[Claude linter] FYI no action required. Autofixes applied.", file=sys.stderr)

    # Exit 0 to allow continuation
    sys.exit(0)


if __name__ == "__main__":
    main()
