# Default (empty) proxy environment for local builds.
# This file is tracked in git and provides the default PROXY_ENV = {}.
#
# On Claude Code web, the session hook overwrites this file with actual
# proxy settings. The overwritten content is ephemeral (session-only) and
# should not be committed.

PROXY_ENV = {}
