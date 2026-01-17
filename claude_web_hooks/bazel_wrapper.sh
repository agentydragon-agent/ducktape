#!/bin/bash
# Bazel wrapper for Claude Code web - sets proxy env vars and checks health
# Reads configuration from environment variables set by bazelisk_setup.py

# Determine repo path for error messages
REPO_PATH="${DUCKTAPE_REPO_ROOT:-~/code/ducktape}"

# Health check: supervisord must be running
if [[ ! -S "$BAZEL_SUPERVISOR_SOCK" ]]; then
    echo "ERROR: supervisord is not running" >&2
    echo "The bazel proxy requires supervisor for process management." >&2
    echo "" >&2
    echo "To start supervisor with the bazel proxy:" >&2
    echo "  cd $REPO_PATH" >&2
    echo "  python3 -m claude_web_hooks.session_start" >&2
    echo "" >&2
    echo "Or to start supervisor manually:" >&2
    echo "  supervisord -c ~/.config/supervisor/supervisord.conf" >&2
    echo "" >&2
    echo "For more information, see:" >&2
    echo "  $REPO_PATH/claude_web_hooks/README.md" >&2
    echo "  tail -20 ~/.cache/claude-code-web/session-start.log" >&2
    exit 1
fi

# Health check: bazel-proxy service must be running
if ! supervisorctl -c "$BAZEL_SUPERVISOR_CONF" status bazel-proxy 2>/dev/null | grep -q RUNNING; then
    echo "ERROR: bazel-proxy service is not running under supervisor" >&2
    echo "" >&2
    echo "To start the bazel proxy:" >&2
    echo "  # Full setup (recommended):" >&2
    echo "  cd $REPO_PATH" >&2
    echo "  python3 -m claude_web_hooks.session_start" >&2
    echo "" >&2
    echo "  # Or just restart the proxy service:" >&2
    echo "  supervisorctl -c $BAZEL_SUPERVISOR_CONF start bazel-proxy" >&2
    echo "" >&2
    echo "To check proxy status and logs:" >&2
    echo "  supervisorctl -c $BAZEL_SUPERVISOR_CONF status" >&2
    echo "  tail -50 ~/.config/supervisor/bazel-proxy.log" >&2
    echo "  tail -50 ~/.config/supervisor/bazel-proxy.err.log" >&2
    echo "" >&2
    echo "For more information, see:" >&2
    echo "  $REPO_PATH/claude_web_hooks/README.md" >&2
    exit 1
fi

export HTTPS_PROXY="$BAZEL_LOCAL_PROXY"
export HTTP_PROXY="$BAZEL_LOCAL_PROXY"
export https_proxy="$BAZEL_LOCAL_PROXY"
export http_proxy="$BAZEL_LOCAL_PROXY"

exec "$BAZELISK_PATH" "$@"
