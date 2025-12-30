# Proxy environment variables for Bazel sandbox actions
# Default: empty (no proxy). On Claude Code web, the session-start hook
# overwrites this file with actual proxy settings.
#
# The lock() rule from rules_python doesn't inherit --action_env values, so
# proxy env must be passed directly via the env attribute.

PROXY_ENV = {}
