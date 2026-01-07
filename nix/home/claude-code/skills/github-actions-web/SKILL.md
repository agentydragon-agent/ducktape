---
name: github-actions-web
description: Run GitHub Actions locally in Claude Code on the web's gVisor container using act with podman. Includes workarounds for sandbox limitations.
---

# GitHub Actions in Claude Code on the Web

This skill explains how to run GitHub Actions locally in Claude Code on the web's container environment. Helper scripts are provided in this skill's directory.

## Quick Start

```bash
# One-time setup (configures podman, installs act)
bash ~/.claude/skills/github-actions-web/setup-podman.sh

# Pull the runner image
podman --log-level=error pull docker.io/catthehacker/ubuntu:act-latest

# List available jobs
bash ~/.claude/skills/github-actions-web/run-act.sh -l

# Run a specific job
bash ~/.claude/skills/github-actions-web/run-act.sh pre-commit
```

## Why These Workarounds?

Claude Code on the web runs in a **gVisor sandbox** with:

1. **No overlay filesystem** - Standard Docker/Podman storage drivers fail
2. **No DNS** - `/etc/resolv.conf` is empty; all traffic must go through proxy
3. **TLS-inspecting proxy** - All HTTPS traffic goes through Anthropic's proxy
4. **Network restrictions** - Container networking (netavark) doesn't work

## Helper Scripts

### `setup-podman.sh`

Configures podman with vfs storage driver, starts the podman service, copies the CA bundle, and installs act.

### `run-act.sh`

Runs act with all necessary workarounds:

- Sets DOCKER_HOST to podman socket
- Passes all proxy environment variables
- Mounts CA bundle for TLS verification
- Uses `--network=host` to bypass netavark
- Uses `--container-options -v` for reliable volume mounts

Usage:

```bash
./run-act.sh JOB_NAME [extra-act-args...]
./run-act.sh -l  # List jobs
```

### `Dockerfile.act-proxy`

Custom image with `global-agent` pre-installed for full Node.js proxy support. Build with:

```bash
cd ~/.claude/skills/github-actions-web
cp /root/.cache/bazel-proxy/combined_ca.pem ca-bundle.pem
podman build --network=host \
  --build-arg HTTP_PROXY="$HTTP_PROXY" \
  --build-arg HTTPS_PROXY="$HTTPS_PROXY" \
  -t act-proxy:latest -f Dockerfile.act-proxy .
```

## What Works

- ✅ Container startup and shell commands
- ✅ Git clone/checkout operations
- ✅ setup-python action (downloads Python from GitHub)
- ✅ pip install with proxy
- ✅ curl/wget with `--proxy` and `--cacert`

## What May Fail

Some Node.js-based actions don't respect `HTTP_PROXY` (e.g., nix-installer-action). These need `global-agent` to route all HTTPS through the proxy:

```bash
# Inside container, install global-agent
export npm_config_proxy="$HTTP_PROXY"
export npm_config_https_proxy="$HTTPS_PROXY"
export npm_config_cafile="/tmp/ca-bundle.pem"
npm install -g global-agent

# Enable for all Node.js processes
export NODE_PATH=$(npm root -g)
export NODE_OPTIONS="-r global-agent/bootstrap"
export GLOBAL_AGENT_HTTP_PROXY="$HTTP_PROXY"
export GLOBAL_AGENT_HTTPS_PROXY="$HTTPS_PROXY"
```

Or use the custom `act-proxy:latest` image which has this pre-configured.

## Troubleshooting

| Error | Solution |
|-------|----------|
| `overlay: mount failed` | Re-run `setup-podman.sh` (configures vfs) |
| `unable to find user root` | Add root to subuid/subgid (done by setup script) |
| `EAI_AGAIN` (DNS fails) | Ensure proxy env vars are passed to act |
| `self-signed certificate` | Mount CA bundle: `--container-options "-v /tmp/ca-bundle.pem:/tmp/ca-bundle.pem:ro"` |
| `netavark: invalid version` | Use `--network=host` |
| Volume lock errors | Run `podman rm --all --force` |

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
