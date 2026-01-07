#!/bin/bash
# Setup script for running act in Claude Code on the web's gVisor container
# This configures podman with vfs storage driver and starts the podman service
#
# Usage: source this script to also export environment variables
#   source ~/.claude/skills/github-actions-web/setup-podman.sh

set -e

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Setting up podman for gVisor ==="

# Install podman if not present
if ! command -v podman &> /dev/null; then
    echo "Installing podman..."
    apt-get update && apt-get install -y podman
fi

# Add root to subuid/subgid (required for user namespace mapping)
grep -q "^root:" /etc/subuid 2>/dev/null || echo "root:100000:65536" >> /etc/subuid
grep -q "^root:" /etc/subgid 2>/dev/null || echo "root:100000:65536" >> /etc/subgid

# Configure podman with vfs storage driver (overlay doesn't work in gVisor)
mkdir -p /etc/containers
cat > /etc/containers/storage.conf << 'EOF'
[storage]
driver = "vfs"
runroot = "/run/containers/storage"
graphroot = "/var/lib/containers/storage"

[storage.options.vfs]
ignore_chown_errors = "true"
EOF

# Kill any existing podman and start fresh
pkill -9 podman 2>/dev/null || true
sleep 1

# Start podman service
podman system service --time=0 unix:///tmp/podman.sock &
sleep 3

# Auto-detect and copy CA bundle
# Try multiple known locations for the CA bundle
CA_BUNDLE=""
for loc in \
    "/root/.cache/bazel-proxy/combined_ca.pem" \
    "/etc/ssl/certs/ca-certificates.crt" \
    "$SSL_CERT_FILE" \
    "$REQUESTS_CA_BUNDLE"; do
    if [ -n "$loc" ] && [ -f "$loc" ]; then
        CA_BUNDLE="$loc"
        break
    fi
done

if [ -n "$CA_BUNDLE" ]; then
    cp "$CA_BUNDLE" /tmp/ca-bundle.pem
    echo "CA bundle copied from $CA_BUNDLE to /tmp/ca-bundle.pem"
else
    echo "WARNING: No CA bundle found. TLS connections may fail."
    echo "Searched: /root/.cache/bazel-proxy/combined_ca.pem, /etc/ssl/certs/ca-certificates.crt"
fi

# Install act if not present
if ! command -v act &> /dev/null && [ ! -f /root/.local/bin/act ]; then
    echo "Installing act..."
    curl -fsSL https://raw.githubusercontent.com/nektos/act/master/install.sh | bash -s -- -b /root/.local/bin
fi

# Export environment variables for proxy (when sourced)
export DOCKER_HOST="unix:///tmp/podman.sock"
export ACT_CA_BUNDLE="/tmp/ca-bundle.pem"

echo ""
echo "=== Setup complete ==="
echo "Podman socket: $DOCKER_HOST"
echo "CA bundle: $ACT_CA_BUNDLE"
echo ""
echo "Next steps:"
echo "  1. Pull runner image: podman pull docker.io/catthehacker/ubuntu:act-latest"
echo "  2. Run jobs: $SKILL_DIR/run-act.sh pre-commit"
