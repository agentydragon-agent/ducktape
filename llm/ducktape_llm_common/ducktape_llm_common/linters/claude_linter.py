#!/usr/bin/env python3
"""Unified Claude Code linter hook that branches based on command-line arguments.

This single binary replaces the separate pre-hook and post-hook binaries.
Usage:
    claude-linter pre     # Run pre-hook (blocks non-fixable violations)
    claude-linter post    # Run post-hook (auto-fixes violations)
"""

import argparse


def main():
    """Main entry point for unified linter hook."""
    parser = argparse.ArgumentParser(
        description="Claude Code linter hook",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modes:
  pre   - Pre-tool-use hook that blocks non-fixable violations
  post  - Post-tool-use hook that auto-fixes violations
  check - Check files for violations (manual mode)
""",
    )

    parser.add_argument("mode", choices=["pre", "post", "check"], help="Mode to run")

    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("files", nargs="*", help="Files to check (for check mode)")

    args = parser.parse_args()

    # Import and run the appropriate hook based on mode
    if args.mode == "pre":
        from ducktape_llm_common.linters.claude_pre_hook import main as pre_main

        pre_main()
    elif args.mode == "post":
        from ducktape_llm_common.linters.claude_post_hook import main as post_main

        post_main()
    elif args.mode == "check":
        # Manual check mode
        from pathlib import Path

        from ducktape_llm_common.linters.claude_rules import ClaudeRulesLinter

        linter = ClaudeRulesLinter()

        # Determine what to check
        if args.files:
            # Check specific files
            results = []
            for file_path in args.files:
                path = Path(file_path)
                if path.is_file() and path.suffix == ".py":
                    result = linter.lint_file(path)
                    if result.has_errors or result.has_warnings:
                        results.append(result)
                elif path.is_dir():
                    results.extend(linter.lint_directory(path))
        else:
            # Check current directory
            results = linter.lint_directory(Path.cwd())

        if results:
            linter.format_violations(results)
            # Exit with error code if violations found
            exit(1)
        else:
            print("✅ No violations found!")
            exit(0)


if __name__ == "__main__":
    main()
