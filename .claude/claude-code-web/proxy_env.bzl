# Proxy environment variables for Bazel sandbox actions.
# When running in Claude Code web, this file is overwritten by the session-start hook
# with actual proxy settings (HTTPS_PROXY, SSL_CERT_FILE, etc.)
#
# The lock() rule from rules_python doesn't inherit --action_env values, so
# proxy env must be passed directly via the env attribute.

PROXY_ENV = {}
