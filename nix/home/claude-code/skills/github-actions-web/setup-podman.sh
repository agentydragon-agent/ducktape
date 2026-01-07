#!/bin/bash
# Setup script for running act in Claude Code on the web's gVisor container
# This configures podman with vfs storage driver and starts the podman service

set -e

echo "=== Setting up podman for gVisor ==="

# Install podman if not present
if ! command -v podman &> /dev/null; then
    echo "Installing podman..."
    apt-get update && apt-get install -y podman
fi

# Add root to subuid/subgid (required for user namespace mapping)
grep -q "^root:" /etc/subuid || echo "root:100000:65536" >> /etc/subuid
grep -q "^root:" /etc/subgid || echo "root:100000:65536" >> /etc/subgid

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

# Copy CA bundle for TLS-inspecting proxy
if [ -f /root/.cache/bazel-proxy/combined_ca.pem ]; then
    cp /root/.cache/bazel-proxy/combined_ca.pem /tmp/ca-bundle.pem
    echo "CA bundle copied to /tmp/ca-bundle.pem"
else
    echo "WARNING: CA bundle not found at /root/.cache/bazel-proxy/combined_ca.pem"
    echo "TLS connections may fail without it"
fi

# Install act if not present
if ! command -v act &> /dev/null && [ ! -f /root/.local/bin/act ]; then
    echo "Installing act..."
    curl -fsSL https://raw.githubusercontent.com/nektos/act/master/install.sh | bash -s -- -b /root/.local/bin
fi

echo "=== Setup complete ==="
echo "Podman socket: unix:///tmp/podman.sock"
echo "CA bundle: /tmp/ca-bundle.pem"
echo ""
echo "Pull the runner image with:"
echo "  podman --log-level=error pull docker.io/catthehacker/ubuntu:act-latest"
