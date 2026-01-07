---
name: github-actions-web
description: Run GitHub Actions locally in Claude Code on the web's gVisor container using act with podman. Includes workarounds for sandbox limitations.
---

# GitHub Actions in Claude Code on the Web

This skill explains how to run GitHub Actions locally in Claude Code on the web's container environment. The container runs on gVisor, which has kernel restrictions that require specific workarounds.

## Quick Reference

If podman is already set up, run act with:

```bash
# Ensure podman socket is running
pgrep -x "podman" > /dev/null || podman system service --time=0 unix:///tmp/podman.sock &
sleep 2

# Copy CA bundle for TLS-inspecting proxy
cp /root/.cache/bazel-proxy/combined_ca.pem /tmp/ca-bundle.pem

# Run a specific job (e.g., pre-commit)
DOCKER_HOST=unix:///tmp/podman.sock /root/.local/bin/act -j pre-commit \
  -P ubuntu-latest=catthehacker/ubuntu:act-latest \
  --network=host \
  --env HTTP_PROXY="$HTTP_PROXY" \
  --env HTTPS_PROXY="$HTTPS_PROXY" \
  --env http_proxy="$http_proxy" \
  --env https_proxy="$https_proxy" \
  --env NO_PROXY="$NO_PROXY" \
  --env no_proxy="$no_proxy" \
  --env NODE_EXTRA_CA_CERTS="/tmp/ca-bundle.pem" \
  --env SSL_CERT_FILE="/tmp/ca-bundle.pem" \
  --env REQUESTS_CA_BUNDLE="/tmp/ca-bundle.pem" \
  --bind /tmp/ca-bundle.pem:/tmp/ca-bundle.pem
```

## Why These Workarounds?

Claude Code on the web runs in a **gVisor sandbox** with:

1. **No overlay filesystem** - Standard Docker/Podman storage drivers fail
2. **Limited syscalls** - Some filesystem operations are restricted
3. **TLS-inspecting proxy** - All HTTPS traffic goes through Anthropic's proxy
4. **Network restrictions** - Container networking (netavark) doesn't work

## Full Setup (One-Time)

### 1. Configure Podman with VFS Storage

```bash
# Install podman if not present
apt-get update && apt-get install -y podman

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
```

### 2. Install act

```bash
curl -fsSL https://raw.githubusercontent.com/nektos/act/master/install.sh | bash -s -- -b /root/.local/bin
```

### 3. Pull Runner Image

```bash
# Start podman API service
pkill -9 podman 2>/dev/null || true
sleep 1
podman system service --time=0 unix:///tmp/podman.sock &
sleep 3

# Pull the act runner image (using --log-level=error to suppress warnings)
podman --log-level=error pull docker.io/catthehacker/ubuntu:act-latest
```

### 4. Verify Setup

```bash
# Quick test that podman works
podman --log-level=error run --rm --network=host alpine:latest /bin/sh -c "echo 'Hello from gVisor!'"
```

## Running Workflows

### List Available Jobs

```bash
DOCKER_HOST=unix:///tmp/podman.sock /root/.local/bin/act -l
```

### Run Specific Job

```bash
# The full command with all workarounds
cp /root/.cache/bazel-proxy/combined_ca.pem /tmp/ca-bundle.pem

DOCKER_HOST=unix:///tmp/podman.sock /root/.local/bin/act -j JOB_NAME \
  -P ubuntu-latest=catthehacker/ubuntu:act-latest \
  --network=host \
  --env HTTP_PROXY="$HTTP_PROXY" \
  --env HTTPS_PROXY="$HTTPS_PROXY" \
  --env http_proxy="$http_proxy" \
  --env https_proxy="$https_proxy" \
  --env NO_PROXY="$NO_PROXY" \
  --env no_proxy="$no_proxy" \
  --env NODE_EXTRA_CA_CERTS="/tmp/ca-bundle.pem" \
  --env SSL_CERT_FILE="/tmp/ca-bundle.pem" \
  --env REQUESTS_CA_BUNDLE="/tmp/ca-bundle.pem" \
  --bind /tmp/ca-bundle.pem:/tmp/ca-bundle.pem
```

Replace `JOB_NAME` with the job name from `act -l` (e.g., `pre-commit`, `bazel-build`).

### Common Jobs in This Repo

```bash
# Pre-commit linting
act -j pre-commit ...

# Frontend build
act -j props-frontend-build ...

# Bazel build and test (requires PostgreSQL service - may not work fully)
act -j bazel-build ...
```

## Troubleshooting

### "overlay: mount failed" or storage errors

Podman is not configured for vfs. Re-run the storage.conf setup.

### "unable to find user root"

Missing subuid/subgid entries. Add them:

```bash
echo "root:100000:65536" >> /etc/subuid
echo "root:100000:65536" >> /etc/subgid
```

### DNS resolution fails (EAI_AGAIN)

Pass proxy environment variables to act with `--env HTTP_PROXY="$HTTP_PROXY"` etc.

### "self-signed certificate in certificate chain"

The TLS-inspecting proxy requires the CA bundle. Mount it:

```bash
cp /root/.cache/bazel-proxy/combined_ca.pem /tmp/ca-bundle.pem
# Add to act command:
--env NODE_EXTRA_CA_CERTS="/tmp/ca-bundle.pem" \
--env SSL_CERT_FILE="/tmp/ca-bundle.pem" \
--env REQUESTS_CA_BUNDLE="/tmp/ca-bundle.pem" \
--bind /tmp/ca-bundle.pem:/tmp/ca-bundle.pem
```

### "netavark: invalid version number"

Use `--network=host` to bypass container networking.

### Container cleanup

```bash
# Remove all containers before retrying
podman rm --all --force
```

## What Works vs. What Doesn't

### Works

- Container startup and basic shell commands
- Git clone operations
- Checkout actions
- curl/wget with `--proxy` flag and `--cacert` for CA bundle
- Node.js with `global-agent` installed and `NODE_OPTIONS="-r global-agent/bootstrap"`

### Root Cause: No DNS in Container

The gVisor container has **no DNS** (`/etc/resolv.conf` is empty). All network traffic must go through the HTTP proxy, which handles DNS resolution. This affects:

- Node.js native `https` module (doesn't use HTTP_PROXY)
- Any tool that tries direct DNS resolution

### Solution: global-agent for Node.js

Node.js can be made proxy-aware with `global-agent`:

```bash
# Inside the container, install global-agent
export npm_config_proxy="$HTTP_PROXY"
export npm_config_https_proxy="$HTTPS_PROXY"
export npm_config_cafile="/tmp/ca-bundle.pem"
npm install -g global-agent

# Set up environment
export NODE_PATH=$(npm root -g)
export NODE_OPTIONS="-r global-agent/bootstrap"
export GLOBAL_AGENT_HTTP_PROXY="$HTTP_PROXY"
export GLOBAL_AGENT_HTTPS_PROXY="$HTTPS_PROXY"

# Now Node.js HTTPS works!
node -e "require('https').get('https://api.github.com/', r => console.log(r.statusCode))"
```

### May Not Work (Without global-agent)

- **Actions that download from internet** (setup-python, setup-node, etc.)
- Docker-in-Docker (nested containers)
- Services that require specific networking
- Jobs that need privileged operations
- Large image builds (vfs is slower and uses more disk)

### Advanced: Custom Image with Proxy Support

For full act support, build a custom image with global-agent pre-installed. Create `/tmp/Dockerfile.act-proxy`:

```dockerfile
FROM catthehacker/ubuntu:act-latest

# Copy CA bundle into image
COPY ca-bundle.pem /etc/ssl/certs/custom-ca-bundle.pem

# Configure npm to use proxy and CA bundle
ENV npm_config_cafile=/etc/ssl/certs/custom-ca-bundle.pem
ARG HTTP_PROXY
ARG HTTPS_PROXY
ENV npm_config_proxy=$HTTP_PROXY
ENV npm_config_https_proxy=$HTTPS_PROXY

# Install global-agent globally
RUN npm install -g global-agent

# Set up environment for global-agent and CA bundle
ENV NODE_PATH=/opt/acttoolcache/node/18.20.8/x64/lib/node_modules
ENV NODE_OPTIONS="-r global-agent/bootstrap"
ENV NODE_EXTRA_CA_CERTS=/etc/ssl/certs/custom-ca-bundle.pem
```

Build it:

```bash
cp /root/.cache/bazel-proxy/combined_ca.pem /tmp/ca-bundle.pem
cd /tmp && podman build --network=host \
  --build-arg HTTP_PROXY="$HTTP_PROXY" \
  --build-arg HTTPS_PROXY="$HTTPS_PROXY" \
  -t act-proxy:latest -f Dockerfile.act-proxy .
```

Note: Building is slow with vfs storage driver (can take 5+ minutes).

## Alternative: Direct Testing

For simpler cases, bypass act entirely:

```bash
# Run pre-commit directly
pip install pre-commit==4.0.1
pre-commit run --all-files

# Run Bazel directly
bazel build //...
bazel test //...
```
