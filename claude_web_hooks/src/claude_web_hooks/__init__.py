"""Claude Code web session hooks.

Provides session start hook for Claude Code web environments
that sets up nix, direnv, devenv, and uv.

IMPORTANT: This package must not have any non-stdlib dependencies
because it runs in session-start hooks before package installation.
"""
