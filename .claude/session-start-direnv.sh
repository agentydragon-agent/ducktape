#!/bin/bash
set -e

# Only run in web environments
if [ "$CLAUDE_CODE_REMOTE" != "true" ]; then
    echo "Skipping development environment setup (local environment)"
    exit 0
fi

echo "Setting up development environment for Claude Code on the Web..." >&2

# Install direnv if not already present
if ! command -v direnv &> /dev/null; then
    echo "Installing direnv..." >&2
    DIRENV_VERSION="2.35.0"
    DIRENV_ARCH="linux-amd64"
    curl -sfL "https://github.com/direnv/direnv/releases/download/v${DIRENV_VERSION}/direnv.${DIRENV_ARCH}" \
        -o /usr/local/bin/direnv
    chmod +x /usr/local/bin/direnv
    echo "direnv ${DIRENV_VERSION} installed successfully" >&2
else
    echo "direnv already installed: $(direnv version)" >&2
fi

# Install Nix if not already present
# Note: nix-env/profile installation crashes in containers due to process management
# issues ("cannot get exit status of PID: No child processes").
# However, nix with flakes works fine for fetching pre-built binaries from cache.
NIX_BIN=""
if [ -d "/nix/store" ]; then
    # Find existing nix binary
    NIX_BIN=$(find /nix/store -path "*/bin/nix" -type f 2>/dev/null | head -1)
fi

if [ -z "$NIX_BIN" ]; then
    echo "Installing Nix (flakes-only mode)..." >&2

    # Create nixbld group and users (required by nix installer)
    if ! getent group nixbld > /dev/null 2>&1; then
        groupadd nixbld 2>/dev/null || true
        for i in $(seq 1 10); do
            useradd -g nixbld -G nixbld -M -N -r -s /sbin/nologin "nixbld$i" 2>/dev/null || true
        done
    fi

    # Download and extract nix (the installer will fail at profile step, but that's ok)
    NIX_VERSION="2.33.0"
    TMPDIR=$(mktemp -d)
    curl -sfL "https://releases.nixos.org/nix/nix-${NIX_VERSION}/nix-${NIX_VERSION}-x86_64-linux.tar.xz" \
        -o "$TMPDIR/nix.tar.xz"

    mkdir -p /nix
    tar -xJf "$TMPDIR/nix.tar.xz" -C "$TMPDIR"

    # Copy store contents manually (skip the broken install script)
    cp -a "$TMPDIR/nix-${NIX_VERSION}-x86_64-linux/store"/* /nix/store/ 2>/dev/null || true

    rm -rf "$TMPDIR"

    NIX_BIN=$(find /nix/store -path "*/bin/nix" -type f 2>/dev/null | head -1)
    echo "Nix ${NIX_VERSION} installed (store only)" >&2
else
    echo "Nix already installed" >&2
fi

# Configure nix for flakes
mkdir -p ~/.config/nix
echo "experimental-features = nix-command flakes" > ~/.config/nix/nix.conf

# Fetch pre-commit and alejandra from nixpkgs cache
ALEJANDRA_PATH=""
PRECOMMIT_PATH=""

if [ -n "$NIX_BIN" ]; then
    echo "Fetching tools from nixpkgs cache..." >&2

    # These are pre-built in nixpkgs cache, so no local building required
    ALEJANDRA_PATH=$("$NIX_BIN" path-info nixpkgs#alejandra 2>/dev/null || true)
    # Note: pre-commit from nix has issues with python envs, use pip instead

    if [ -n "$ALEJANDRA_PATH" ]; then
        echo "  alejandra: $ALEJANDRA_PATH" >&2
    fi
fi

# Allow all .envrc files in the project
if [ -n "$CLAUDE_PROJECT_DIR" ]; then
    cd "$CLAUDE_PROJECT_DIR"
    echo "Allowing .envrc files in project..." >&2
    if find . -name ".envrc" -type f 2>/dev/null | grep -q ".envrc"; then
        find . -name ".envrc" -type f | while read envrc; do
            echo "  Allowing $envrc" >&2
            direnv allow "$(dirname "$envrc")" 2>/dev/null || echo "    (failed to allow)" >&2
        done
    else
        echo "  No .envrc files found" >&2
    fi
fi

# Output environment setup to STDOUT for Claude Code to capture
echo "# Nix and direnv setup for Claude Code on the Web"
if [ -n "$NIX_BIN" ]; then
    NIX_BIN_DIR=$(dirname "$NIX_BIN")
    echo "export PATH=\"$NIX_BIN_DIR:\$PATH\""
fi
if [ -n "$ALEJANDRA_PATH" ]; then
    echo "export PATH=\"$ALEJANDRA_PATH/bin:\$PATH\""
fi
echo "if command -v direnv &> /dev/null; then"
echo "    eval \"\$(direnv hook bash)\""
echo "fi"

echo "" >&2
echo "Development environment setup complete:" >&2
echo "  ✓ direnv: $(direnv version 2>/dev/null || echo 'installed')" >&2
if [ -n "$NIX_BIN" ]; then
    echo "  ✓ nix: $("$NIX_BIN" --version 2>/dev/null || echo 'installed')" >&2
else
    echo "  ✗ nix: failed to install" >&2
fi
if [ -n "$ALEJANDRA_PATH" ]; then
    echo "  ✓ alejandra: available" >&2
else
    echo "  ✗ alejandra: not available" >&2
fi
echo "  ⚠ devenv: cannot build (container limitation)" >&2
echo "" >&2
echo "Note: 'use devenv' in .envrc will error but other commands work." >&2
echo "      Use 'nix run nixpkgs#package' to run tools from nixpkgs." >&2
