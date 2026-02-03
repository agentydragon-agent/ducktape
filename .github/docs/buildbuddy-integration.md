# BuildBuddy Integration

This document explains how BuildBuddy remote cache and remote build execution (RBE) are set up for both GitHub Copilot and Claude Code hooks.

## Overview

BuildBuddy provides:

- **Remote Cache**: Speeds up builds by sharing build artifacts across machines and developers
- **Remote Build Execution (RBE)**: Offloads build actions to BuildBuddy workers, enabling parallel execution at scale
- **Build Event Stream**: Provides detailed build analytics and visualization

## Architecture

Both GitHub Copilot and Claude Code hooks use the same core setup script:

```
tools/setup-buildbuddy.sh
```

This script:

1. Checks for `BUILDBUDDY_API_KEY` environment variable
2. Writes configuration to `~/.config/bazel/buildbuddy.bazelrc`
3. Adds `try-import` line to `~/.bazelrc`
4. Enables remote execution with the `//:rbe_linux_x64` platform

## GitHub Copilot Setup

Location: `.github/workflows/copilot-setup-steps.yml`

The setup happens through a chain of actions:

1. **Setup Bazel** (`.github/actions/setup-bazel`)
   - Receives `BUILDBUDDY_API_KEY` from repository secrets
   - Calls Setup BuildBuddy action

2. **Setup BuildBuddy** (`.github/actions/setup-buildbuddy`)
   - Runs `tools/setup-buildbuddy.sh` with the API key
   - Skips silently if API key is not provided (graceful degradation)

3. **Bazel Repo Cache** (`.github/actions/bazel-repo-cache`)
   - Sets up Bazelisk
   - Enables toolchain auto-detection for GHA runners
   - Restores Bazel repository cache

### Verification

The copilot-setup-steps workflow includes verification steps that check:

- BuildBuddy configuration exists at `~/.config/bazel/buildbuddy.bazelrc`
- Remote execution is enabled
- Remote cache is enabled
- Bazel toolchain auto-detection is enabled

## Claude Code Hooks Setup

Location: `tools/claude_hooks/session_start.py`

The setup happens in `run_web_mode()`:

```python
buildbuddy: buildbuddy_setup.BuildbuddySetup | BaseException = results[5]
```

The `buildbuddy_setup.setup_buildbuddy()` function:

1. Reads `BUILDBUDDY_API_KEY` from environment
2. Calls `tools/setup-buildbuddy.sh` via subprocess
3. Returns `BuildbuddySetup(configured=True/False)`

## Configuration Details

The generated `~/.config/bazel/buildbuddy.bazelrc` contains:

```bazelrc
# BuildBuddy configuration (auto-generated)
build --bes_results_url=https://app.buildbuddy.io/invocation/
build --bes_backend=grpcs://remote.buildbuddy.io
common --remote_cache=grpcs://remote.buildbuddy.io
common --remote_timeout=10m
common --remote_header=x-buildbuddy-api-key=${BUILDBUDDY_API_KEY}
common --remote_cache_compression
build --noslim_profile
build --experimental_profile_include_target_label
build --experimental_profile_include_primary_output

# Remote execution: actions run on BuildBuddy workers, falling back to local.
build --remote_executor=grpcs://remote.buildbuddy.io
build --extra_execution_platforms=//:rbe_linux_x64
build --spawn_strategy=remote,local
build --jobs=50
build --remote_download_minimal
```

## RBE Container Image

The RBE worker image is defined in `tools/rbe_image/Dockerfile` and built by `.github/workflows/rbe-image.yml`.

Base: BuildBuddy's `rbe-ubuntu24-04` image
Additions:

- Rust toolchain dependencies
- GHC's libtinfo5
- Chromium shared libraries

Image location: `ghcr.io/agentydragon/rbe-worker`

The platform configuration is in the root `BUILD.bazel`:

```python
platform(
    name = "rbe_linux_x64",
    exec_properties = {
        "container-image": "docker://ghcr.io/agentydragon/rbe-worker:latest",
        "OSFamily": "Linux",
    },
)
```

## Bazel Toolchain Auto-Detection

Both setups enable C++ toolchain auto-detection on Linux systems:

**GitHub Actions**: Set in `.github/actions/bazel-repo-cache`

```bash
echo "build --repo_env=BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=0" >> ~/.bazelrc
```

**Claude Code**: Uses wrapper that respects system Bazel installation

The workspace `.bazelrc` normally sets `BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=1` to prevent Nix store paths from leaking into builds. Both GitHub Actions and Claude Code override this to use the system GCC.

## Key Differences

| Feature              | GitHub Copilot               | Claude Code Hooks         |
| -------------------- | ---------------------------- | ------------------------- |
| API Key Source       | GitHub Secrets               | Environment variable      |
| Network              | Direct internet              | Auth proxy                |
| Bazelisk             | bazelbuild/setup-bazelisk@v3 | Manual download + wrapper |
| Props Docker Network | `props-agents`               | `host`                    |
| Verification         | Explicit verification step   | Logged to session context |

## Shared Components

Both setups share:

- `tools/setup-buildbuddy.sh` - Core configuration script
- `~/.config/bazel/buildbuddy.bazelrc` - Generated config file
- `//:rbe_linux_x64` platform - RBE worker specification
- Graceful degradation when API key is unavailable

## Troubleshooting

### BuildBuddy not configured

**Symptom**: Verification shows "BuildBuddy: not configured"

**Cause**: `BUILDBUDDY_API_KEY` secret is not set in repository settings

**Solution**:

1. Get API key from BuildBuddy dashboard
2. Add as repository secret: Settings → Secrets → Actions → New repository secret
3. Name: `BUILDBUDDY_API_KEY`

### RBE builds failing

**Symptom**: Build actions fail with "No such container image" or similar

**Cause**: RBE image not available or outdated

**Solution**:

1. Check image exists: `docker pull ghcr.io/agentydragon/rbe-worker:latest`
2. Rebuild image if needed: `.github/workflows/rbe-image.yml`
3. Update platform configuration in `BUILD.bazel` if using custom image tag

### Toolchain detection issues

**Symptom**: Builds fail with "no matching toolchain found"

**Cause**: `BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=0` not set

**Solution**: Verify `~/.bazelrc` contains the override:

```bash
grep BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN ~/.bazelrc
```

## Future Improvements

Potential areas for deduplication and improvement:

1. **Shared precommit setup**: Extract common pre-commit installation logic into a reusable script
2. **Unified environment setup**: Create a common setup library used by both Claude hooks and GitHub Actions
3. **BuildBuddy health checks**: Add periodic verification that remote cache is working
4. **RBE image auto-detection**: Automatically detect and use the latest RBE image version
