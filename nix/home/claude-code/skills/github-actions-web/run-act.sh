#!/bin/bash
# Run act with all workarounds for Claude Code on the web's gVisor container
# Usage: ./run-act.sh [job-name] [extra-act-args...]
#
# Examples:
#   ./run-act.sh pre-commit
#   ./run-act.sh bazel-build --verbose
#   ./run-act.sh -l  # List jobs

set -e

# Default job (empty means list jobs or run default)
JOB="${1:--l}"
shift 2>/dev/null || true

# Ensure CA bundle exists
if [ ! -f /tmp/ca-bundle.pem ]; then
    if [ -f /root/.cache/bazel-proxy/combined_ca.pem ]; then
        cp /root/.cache/bazel-proxy/combined_ca.pem /tmp/ca-bundle.pem
    else
        echo "ERROR: CA bundle not found. Run setup-podman.sh first."
        exit 1
    fi
fi

# Ensure podman socket is running
if [ ! -S /tmp/podman.sock ]; then
    echo "Podman socket not found. Starting podman service..."
    podman system service --time=0 unix:///tmp/podman.sock &
    sleep 3
fi

# Clean up any stale containers
podman rm --all --force 2>/dev/null || true

# Determine act binary location
ACT_BIN="${ACT_BIN:-/root/.local/bin/act}"
if [ ! -x "$ACT_BIN" ]; then
    ACT_BIN="$(which act 2>/dev/null || echo "")"
fi
if [ -z "$ACT_BIN" ] || [ ! -x "$ACT_BIN" ]; then
    echo "ERROR: act not found. Run setup-podman.sh first."
    exit 1
fi

# Build the act command with all workarounds
if [ "$JOB" = "-l" ]; then
    # List jobs
    DOCKER_HOST=unix:///tmp/podman.sock "$ACT_BIN" -l "$@"
else
    # Run specific job
    DOCKER_HOST=unix:///tmp/podman.sock "$ACT_BIN" -j "$JOB" \
        -P ubuntu-latest=catthehacker/ubuntu:act-latest \
        --network=host \
        --env HTTP_PROXY="$HTTP_PROXY" \
        --env HTTPS_PROXY="$HTTPS_PROXY" \
        --env http_proxy="$http_proxy" \
        --env https_proxy="$https_proxy" \
        --env NO_PROXY="$NO_PROXY" \
        --env no_proxy="$no_proxy" \
        --env GLOBAL_AGENT_HTTP_PROXY="$GLOBAL_AGENT_HTTP_PROXY" \
        --env GLOBAL_AGENT_HTTPS_PROXY="$GLOBAL_AGENT_HTTPS_PROXY" \
        --env NODE_EXTRA_CA_CERTS="/tmp/ca-bundle.pem" \
        --env SSL_CERT_FILE="/tmp/ca-bundle.pem" \
        --env REQUESTS_CA_BUNDLE="/tmp/ca-bundle.pem" \
        --env GIT_SSL_CAINFO="/tmp/ca-bundle.pem" \
        --container-options "-v /tmp/ca-bundle.pem:/tmp/ca-bundle.pem:ro" \
        "$@"
fi
