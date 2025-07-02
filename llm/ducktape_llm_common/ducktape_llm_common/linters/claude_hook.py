#!/usr/bin/env python3
"""Claude Code post-tool-use hook for linting edited files.

This hook runs after Claude uses Write, Edit, or MultiEdit tools to modify files,
ensuring code quality standards are maintained.
"""

import json
import logging
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import platformdirs

from ducktape_llm_common.linters.claude_rules import ClaudeRulesLinter

try:
    import tomllib
except ImportError:
    import tomli as tomllib

# Set up logging - only to file, not stderr (which is used for hook output)
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("/tmp/claude-linter-hook.log")],
)
logger = logging.getLogger(__name__)


def generate_precommit_config(pre_commit_section: dict) -> Path:
    """Generate a temporary pre-commit config file from TOML config.

    Returns:
        Path to the temporary config file
    """
    import yaml

    # Convert TOML format to pre-commit YAML format
    config: dict[str, list] = {"repos": []}

    for repo in pre_commit_section.get("repos", []):
        repo_dict = {"repo": repo["repo"], "rev": repo["rev"], "hooks": []}

        for hook in repo.get("hooks", []):
            hook_dict = {"id": hook["id"]}
            if "name" in hook:
                hook_dict["name"] = hook["name"]
            if "files" in hook:
                hook_dict["files"] = hook["files"]
            if "args" in hook:
                hook_dict["args"] = hook["args"]
            repo_dict["hooks"].append(hook_dict)

        config["repos"].append(repo_dict)

    # Write to temporary file - delete=False so we can use it after exiting context
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
    yaml.dump(config, f)
    f.close()
    return Path(f.name)


def fix_text_issues(file_path: Path, log_file: Path) -> tuple[bool, str]:
    """Fix common text issues using pre-commit hooks.

    Returns:
        tuple of (changes_made, error_message)
    """
    # Load config from XDG config directory
    config_dir = Path(platformdirs.user_config_dir("claude-linter"))
    config_path = config_dir / "config.toml"

    pre_commit_config = None
    temp_config_path = None

    if config_path.exists():
        with open(config_path, "rb") as f:
            config = tomllib.load(f)
            pre_commit_config = config.get("pre-commit")

    if not pre_commit_config:
        # Fall back to text-fixes.yaml if no config
        fallback_path = Path(__file__).parent / "text-fixes.yaml"
        if fallback_path.exists():
            config_path = fallback_path
        else:
            with open(log_file, "a") as f:
                f.write(f"No text fixes config found in {config_dir} or {fallback_path}\n")
            return False, ""
    else:
        # Generate temporary pre-commit config from TOML
        temp_config_path = generate_precommit_config(pre_commit_config)
        config_path = temp_config_path

    # Run pre-commit with our custom config on the specific file
    cmd = ["pre-commit", "run", "--config", str(config_path), "--files", str(file_path)]

    with open(log_file, "a") as f:
        f.write(f"Running command: {' '.join(cmd)}\n")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,  # 30 second timeout
        )

        with open(log_file, "a") as f:
            f.write(f"Pre-commit exit code: {result.returncode}\n")
            f.write(f"Pre-commit stdout: {result.stdout}\n")
            f.write(f"Pre-commit stderr: {result.stderr}\n")

        # Exit code 0 = no changes needed
        # Exit code 1 = changes were made
        # Exit code > 1 = error occurred
        if result.returncode == 0:
            return False, ""
        elif result.returncode == 1:
            # Changes were made
            return True, ""
        else:
            # Error occurred
            return False, result.stderr or "Unknown error running pre-commit"

    except subprocess.TimeoutExpired:
        with open(log_file, "a") as f:
            f.write("Pre-commit command timed out after 30 seconds\n")
        return False, "Text fixing timed out"
    except Exception as e:
        with open(log_file, "a") as f:
            f.write(f"Exception running pre-commit: {e}\n")
        return False, str(e)
    finally:
        # Clean up temporary config file if we generated one
        if temp_config_path and temp_config_path.exists():
            try:
                temp_config_path.unlink()
            except Exception:
                pass


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

    # Collect files to process
    files_to_lint = set()
    files_to_fix = set()

    # For Write tool, get the file path
    file_path = tool_params.get("file_path")
    if file_path:
        file_path_obj = Path(file_path)
        # Python files get linted
        if file_path.endswith(".py"):
            files_to_lint.add(file_path_obj)
        # All files get text fixes
        files_to_fix.add(file_path_obj)

    if not files_to_lint:
        # No Python files to lint
        with open(log_file, "a") as f:
            f.write("No Python files to lint\n")

    with open(log_file, "a") as f:
        f.write(f"Files to lint: {[str(f) for f in files_to_lint]}\n")
        f.write(f"Files to fix: {[str(f) for f in files_to_fix]}\n")

    # Collect linting results
    all_results = []

    if files_to_lint:
        # Create linter instance with treat_all_as_errors=True for Write operations
        try:
            linter = ClaudeRulesLinter(treat_all_as_errors=True)
            with open(log_file, "a") as f:
                f.write("Linter instance created with treat_all_as_errors=True\n")
        except Exception as e:
            with open(log_file, "a") as f:
                f.write(f"Error creating linter: {e}\n")
            sys.exit(1)

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

    # Run text fixes on all files
    text_fix_errors = []
    files_fixed = 0

    for file_path in files_to_fix:
        if not file_path.exists():
            with open(log_file, "a") as f:
                f.write(f"File does not exist for text fixes: {file_path}\n")
            continue

        with open(log_file, "a") as f:
            f.write(f"Running text fixes on: {file_path}\n")

        changes_made, error_msg = fix_text_issues(file_path, log_file)

        if error_msg:
            text_fix_errors.append(f"{file_path}: {error_msg}")
            with open(log_file, "a") as f:
                f.write(f"Text fix error: {error_msg}\n")
        elif changes_made:
            files_fixed += 1
            with open(log_file, "a") as f:
                f.write(f"Text fixes applied to: {file_path}\n")

    # Report text fix errors if any
    if text_fix_errors:
        print("\n⚠️  Text fixing errors:", file=sys.stderr)
        for error in text_fix_errors:
            print(f"  - {error}", file=sys.stderr)
        # Don't block execution for text fix errors

    # Success message
    messages = []
    if files_to_lint:
        messages.append(f"✅ Linter passed for {len(files_to_lint)} Python file(s)")
    if files_fixed > 0:
        messages.append(f"🔧 Fixed text issues in {files_fixed} file(s)")

    if messages:
        print(" | ".join(messages))

    sys.exit(0)


if __name__ == "__main__":
    main()
