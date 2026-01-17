#!/bin/bash
# Bazel wrapper for Claude Code web - sets proxy env vars and checks health
# Reads configuration from environment variables set by bazelisk_setup.py

REPO_PATH="${DUCKTAPE_REPO_ROOT:-~/code/ducktape}"

# Health checks
if [[ ! -S "$BAZEL_SUPERVISOR_SOCK" ]]; then
    echo "✗ supervisord not running" >&2
    echo "✗ bazel-proxy not running" >&2
    echo "" >&2
    echo "To start:" >&2
    echo "  cd $REPO_PATH" >&2
    echo "  python3 -m claude_web_hooks.session_start" >&2
    echo "" >&2
    echo "Documentation: $REPO_PATH/claude_web_hooks/README.md" >&2
    echo "Setup log: ~/.cache/claude-code-web/session-start.log" >&2
    exit 1
fi

if ! supervisorctl -c "$BAZEL_SUPERVISOR_CONF" status bazel-proxy 2>/dev/null | grep -q RUNNING; then
    echo "✓ supervisord running" >&2
    echo "✗ bazel-proxy not running" >&2
    echo "" >&2
    echo "To start proxy:" >&2
    echo "  cd $REPO_PATH" >&2
    echo "  python3 -m claude_web_hooks.session_start" >&2
    echo "" >&2
    echo "Or restart service:" >&2
    echo "  supervisorctl -c $BAZEL_SUPERVISOR_CONF start bazel-proxy" >&2
    echo "" >&2
    echo "Logs: ~/.config/supervisor/bazel-proxy.{log,err.log}" >&2
    echo "Documentation: $REPO_PATH/claude_web_hooks/README.md" >&2
    exit 1
fi

export HTTPS_PROXY="$BAZEL_LOCAL_PROXY"
export HTTP_PROXY="$BAZEL_LOCAL_PROXY"
export https_proxy="$BAZEL_LOCAL_PROXY"
export http_proxy="$BAZEL_LOCAL_PROXY"

exec "$BAZELISK_PATH" "$@"
