#!/bin/bash
# Run act with all workarounds for Claude Code on the web's gVisor container
# Auto-detects CA bundle, proxy settings, and custom image if available
#
# Usage: ./run-act.sh [job-name] [extra-act-args...]
#
# Examples:
#   ./run-act.sh pre-commit
#   ./run-act.sh bazel-build --verbose
#   ./run-act.sh -l  # List jobs

set -e

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Default job (empty means list jobs or run default)
JOB="${1:--l}"
shift 2>/dev/null || true

# Auto-detect CA bundle from multiple locations
CA_BUNDLE="${ACT_CA_BUNDLE:-}"
if [ -z "$CA_BUNDLE" ] || [ ! -f "$CA_BUNDLE" ]; then
    for loc in \
        "/tmp/ca-bundle.pem" \
        "/root/.cache/bazel-proxy/combined_ca.pem" \
        "/etc/ssl/certs/ca-certificates.crt" \
        "$SSL_CERT_FILE" \
        "$REQUESTS_CA_BUNDLE"; do
        if [ -n "$loc" ] && [ -f "$loc" ]; then
            CA_BUNDLE="$loc"
            break
        fi
    done
fi

if [ -z "$CA_BUNDLE" ] || [ ! -f "$CA_BUNDLE" ]; then
    echo "ERROR: CA bundle not found. Run setup-podman.sh first or set ACT_CA_BUNDLE."
    exit 1
fi

# Copy to /tmp if not already there (for container mount)
if [ "$CA_BUNDLE" != "/tmp/ca-bundle.pem" ]; then
    cp "$CA_BUNDLE" /tmp/ca-bundle.pem
    CA_BUNDLE="/tmp/ca-bundle.pem"
fi

# Ensure podman socket is running
if [ ! -S /tmp/podman.sock ]; then
    echo "Podman socket not found. Starting podman service..."
    pkill -9 podman 2>/dev/null || true
    sleep 1
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

# Check if custom act-proxy image exists (has global-agent for full proxy support)
RUNNER_IMAGE="catthehacker/ubuntu:act-latest"
PULL_FLAG=""
if podman image exists localhost/act-proxy:latest 2>/dev/null; then
    echo "Using custom act-proxy:latest image (with global-agent)"
    RUNNER_IMAGE="localhost/act-proxy:latest"
    PULL_FLAG="--pull=false"
else
    echo "Using standard catthehacker/ubuntu:act-latest image"
    echo "Note: Some Node.js actions may fail. Build act-proxy:latest for full support."
fi

# Auto-detect proxy environment variables
# These should be set by the Claude Code web environment
HTTP_PROXY="${HTTP_PROXY:-}"
HTTPS_PROXY="${HTTPS_PROXY:-}"
http_proxy="${http_proxy:-$HTTP_PROXY}"
https_proxy="${https_proxy:-$HTTPS_PROXY}"
NO_PROXY="${NO_PROXY:-localhost,127.0.0.1}"
no_proxy="${no_proxy:-$NO_PROXY}"
GLOBAL_AGENT_HTTP_PROXY="${GLOBAL_AGENT_HTTP_PROXY:-$HTTP_PROXY}"
GLOBAL_AGENT_HTTPS_PROXY="${GLOBAL_AGENT_HTTPS_PROXY:-$HTTPS_PROXY}"

# Build the act command with all workarounds
export DOCKER_HOST="unix:///tmp/podman.sock"

if [ "$JOB" = "-l" ]; then
    # List jobs
    "$ACT_BIN" -l "$@"
else
    echo "Running job: $JOB"
    echo "CA bundle: $CA_BUNDLE"
    echo ""

    # Run specific job with all workarounds
    # shellcheck disable=SC2086
    "$ACT_BIN" -j "$JOB" \
        -P "ubuntu-latest=$RUNNER_IMAGE" \
        $PULL_FLAG \
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
