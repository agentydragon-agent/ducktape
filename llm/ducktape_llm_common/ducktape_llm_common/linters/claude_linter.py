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
""",
    )

    parser.add_argument("mode", choices=["pre", "post"], help="Hook mode to run")

    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    # Import and run the appropriate hook based on mode
    if args.mode == "pre":
        from ducktape_llm_common.linters.claude_pre_hook import main as pre_main

        pre_main()
    elif args.mode == "post":
        from ducktape_llm_common.linters.claude_post_hook import main as post_main

        post_main()


if __name__ == "__main__":
    main()
