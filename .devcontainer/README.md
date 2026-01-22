# Development Container Configuration

This directory contains configuration for GitHub Codespaces, Visual Studio Code Dev Containers, and other tools that support the [Development Container specification](https://containers.dev/).

## Files

- **devcontainer.json**: Main configuration file defining the development environment
- **setup.sh**: Post-create setup script that runs when the container is created
- **ENVIRONMENT_SETUP.md**: Detailed documentation of environment setup decisions and options

## Quick Start

### GitHub Codespaces

1. Click "Code" → "Create codespace on main"
2. Wait for container to build and setup script to complete
3. The environment will be configured automatically

### VS Code Dev Containers

1. Install the "Dev Containers" extension
2. Open this repository in VS Code
3. Click "Reopen in Container" when prompted
4. Wait for setup to complete

## What Gets Configured

The setup script will:

1. **Install Bazelisk** (if not already available)
2. **Install claude_hooks package** from tools/claude_hooks
3. **Run session start hook** in "standard" mode which:
   - Installs git pre-commit hooks
   - Installs development tools (opentofu, tflint, etc.)
   - Optionally installs Nix

The setup is optimized for standard environments with:
- Direct internet access (no proxy)
- Pre-installed Docker/Podman
- Standard networking

## Environment Variables

Key environment variables set by the configuration:

- `CLAUDE_HOOKS_MODE=standard` - Use standard mode (not web/cli mode)
- `CLAUDE_HOOKS_SKIP_PROXY=1` - Skip proxy setup (not needed)
- `CLAUDE_HOOKS_SKIP_BAZELISK=1` - Skip bazelisk installation (pre-installed)
- `CLAUDE_HOOKS_SKIP_PODMAN=1` - Skip podman setup (pre-installed)
- `CLAUDE_PROJECT_DIR` - Path to project root
- `CLAUDE_ENV_FILE` - Path to generated environment file

## Using the Environment

After container creation, source the environment file:

```bash
source /tmp/ducktape-env.sh
```

Or add to your shell RC file:

```bash
echo '[ -f /tmp/ducktape-env.sh ] && source /tmp/ducktape-env.sh' >> ~/.bashrc
```

## Troubleshooting

### Setup fails

Check the session start log:

```bash
tail -100 ~/.cache/claude-code-web/session-start.log
```

### Git hooks not installed

Run manually:

```bash
pre-commit install
```

### Tools missing

Re-run setup script:

```bash
bash .devcontainer/setup.sh
```

## Customization

To customize the environment:

1. Edit `devcontainer.json` to change features, settings, or environment variables
2. Edit `setup.sh` to modify the setup process
3. Rebuild the container

## See Also

- [ENVIRONMENT_SETUP.md](ENVIRONMENT_SETUP.md) - Detailed setup documentation
- [tools/claude_hooks/README.md](../tools/claude_hooks/README.md) - Claude hooks documentation
- [Development Containers specification](https://containers.dev/)
