# Default (empty) proxy environment for non-Claude-Code-web environments.
# This file is tracked in git and provides the fallback PROXY_ENV.
#
# On Claude Code web, the session hook generates proxy_env.bzl with actual
# proxy settings. That file is gitignored.

PROXY_ENV = {}
