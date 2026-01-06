"""Claude Code web session hooks and Bazel proxy.

Provides:
- Session start hook for Claude Code web environments
- Local proxy for TLS-inspecting proxies (Bazel BCR access)
- Nix/devenv setup utilities (currently disabled)

IMPORTANT: This package must not have any non-stdlib dependencies
because it runs in session-start hooks before package installation.
"""

from claude_web_hooks.proxy import main as proxy_main

__all__ = ["proxy_main"]
