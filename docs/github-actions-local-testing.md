# Local GitHub Actions Testing with `act`

This document describes how to test GitHub Actions workflows locally using [act](https://github.com/nektos/act).

## Prerequisites

1. **Docker**: `act` runs workflows in Docker containers

   ```bash
   docker --version
   ```

2. **act**: Install via one of these methods:

   ```bash
   # Via Nix (recommended in this repo)
   nix run nixpkgs#act -- --version

   # Via install script
   curl -fsSL https://raw.githubusercontent.com/nektos/act/master/install.sh | bash

   # Via Homebrew (macOS)
   brew install act
   ```

## Claude Code on the Web Container Setup

When running in a Claude Code web container (sandboxed environment), special setup is required:

### Install Docker and act

```bash
# Install Docker
apt-get update && apt-get install -y docker.io

# Install act
curl -fsSL https://raw.githubusercontent.com/nektos/act/master/install.sh | bash -s -- -b /root/.local/bin
```

### Start Docker Daemon

The container environment doesn't support iptables/NAT, so Docker must run with networking disabled:

```bash
# Start dockerd with vfs storage and no networking
nohup dockerd --iptables=false --bridge=none -s vfs > /tmp/dockerd.log 2>&1 &
sleep 5
docker info
```

### Limitations

**The vfs storage driver doesn't support extended attributes (xattr)**. This means:

- **catthehacker/ubuntu:act-\*** images won't pull (gstreamer has files with security.capability xattr)
- Basic images like `ubuntu:24.04` and `node:22-slim` work but lack GitHub Actions tools
- Running act with basic images will fail on actions that require Node.js (most actions)

### Alternative: Direct Testing

Instead of act, test CI steps directly in the container:

```bash
# Install Python and pre-commit
apt-get install -y python3 python3-pip
pip install pre-commit==4.0.1

# Run pre-commit (same as CI)
pre-commit run --all-files

# Run Bazel builds
bazel build //...
bazel test //...
```

### Full act Testing (Requires Real Docker)

For full act testing with catthehacker images, use a machine with proper Docker support:

- Native Linux with overlay2 storage driver
- macOS with Docker Desktop
- WSL2 with Docker Desktop

## Basic Usage

```bash
# List all jobs in all workflows
act -l

# Dry run (show what would run, no execution)
act -n

# Run all jobs triggered by push
act push

# Run a specific job
act -j pre-commit
act -j bazel-build
act -j props-frontend-build

# Run with a specific Docker image (recommended for consistency)
act -P ubuntu-latest=catthehacker/ubuntu:act-latest
```

## Recommended Images

The default `act` images are minimal. For better compatibility with this repo's CI:

```bash
# Medium image (smaller, faster, handles most cases)
act -P ubuntu-latest=catthehacker/ubuntu:act-latest

# Full image (larger, more tools pre-installed)
act -P ubuntu-latest=catthehacker/ubuntu:full-latest
```

Pull images first for faster subsequent runs:

```bash
docker pull catthehacker/ubuntu:act-latest
```

## Testing Specific Workflows

### Pre-commit Job

```bash
act -j pre-commit -P ubuntu-latest=catthehacker/ubuntu:act-latest
```

Note: Some hooks require additional tools (terraform, tflint, flux, checkov). The CI
installs these via Nix.

### Frontend Build

```bash
act -j props-frontend-build -P ubuntu-latest=catthehacker/ubuntu:act-latest
```

### Bazel Build and Test

```bash
act -j bazel-build -P ubuntu-latest=catthehacker/ubuntu:act-latest
```

Note: This job requires Docker services (PostgreSQL). Use `--container-options` for
Docker-in-Docker support if needed.

## Environment Variables and Secrets

```bash
# Pass secrets file
act -s GITHUB_TOKEN="$(gh auth token)" --secret-file .secrets

# Pass environment variables
act --env FOO=bar
```

## Debugging

```bash
# Verbose output
act -v

# Very verbose
act -vv

# Keep containers running after failure
act --reuse

# Interactive debugging (drops into shell on failure)
# Add to workflow: run: /bin/bash (and use --reuse)
```

## Common Issues

### No Docker Connection

```
Couldn't get a valid docker connection: no DOCKER_HOST
```

Ensure Docker is running:

```bash
docker info
```

### Services Not Working

GitHub Actions services (like PostgreSQL) require special handling in `act`.
The container needs Docker-in-Docker capabilities:

```bash
act -j bazel-build --privileged --container-options "--add-host=host.docker.internal:host-gateway"
```

### Composite Actions with Local Paths

`act` handles composite actions (like `./.github/actions/setup-nix-direnv`) correctly
as long as they're in the repo.

## CI Workflow Jobs

| Job                    | Description                               | Notes                       |
| ---------------------- | ----------------------------------------- | --------------------------- |
| `pre-commit`           | Linting (ruff, prettier, terraform, etc.) | Requires Nix for some hooks |
| `ansible-lint-full`    | Ansible validation                        | Requires ansible-core       |
| `props-frontend-build` | Frontend build + svelte-check             | Uses Bazel                  |
| `visual-regression`    | Puppeteer visual tests                    | Uses Bazel                  |
| `bazel-build`          | Full build, lint, test                    | Requires PostgreSQL service |

## Quick Test Script

Create a script `.github/scripts/test-local.sh`:

```bash
#!/bin/bash
set -e

JOB=${1:-pre-commit}
IMAGE=${ACT_IMAGE:-catthehacker/ubuntu:act-latest}

echo "Testing job: $JOB"
echo "Using image: $IMAGE"

act -j "$JOB" -P "ubuntu-latest=$IMAGE" --reuse
```

Usage:

```bash
.github/scripts/test-local.sh pre-commit
.github/scripts/test-local.sh bazel-build
```
