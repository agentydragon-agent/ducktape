#!/bin/bash
set -e

# Only run in web environments
if [ "$CLAUDE_CODE_REMOTE" != "true" ]; then
    echo "Skipping development environment setup (local environment)"
    exit 0
fi

echo "Setting up development environment for Claude Code on the Web..."

# Install Nix if not already present
if ! command -v nix &> /dev/null; then
    echo "Installing Nix (single-user mode)..."
    curl -L https://nixos.org/nix/install | sh -s -- --no-daemon

    # Source Nix profile for this script
    . ~/.nix-profile/etc/profile.d/nix.sh

    echo "Nix installed successfully"
fi

# Ensure Nix profile is loaded
if [ -f ~/.nix-profile/etc/profile.d/nix.sh ]; then
    . ~/.nix-profile/etc/profile.d/nix.sh
fi

# Enable Nix flakes and nix-command (required by devenv)
if [ ! -f ~/.config/nix/nix.conf ] || ! grep -q "experimental-features" ~/.config/nix/nix.conf; then
    echo "Enabling Nix flakes..."
    mkdir -p ~/.config/nix
    echo "experimental-features = nix-command flakes" >> ~/.config/nix/nix.conf
fi

# Install devenv if not already present
if ! command -v devenv &> /dev/null; then
    echo "Installing devenv..."
    nix profile install --accept-flake-config nixpkgs#devenv
    echo "devenv installed successfully"
fi

# Install direnv if not already present
if ! command -v direnv &> /dev/null; then
    echo "Installing direnv..."
    curl -sfL https://direnv.net/install.sh | bash
    echo "direnv installed successfully"
fi

# Allow all .envrc files in the project
cd "$CLAUDE_PROJECT_DIR"
echo "Allowing .envrc files..."
find . -name ".envrc" -type f | while read envrc; do
    echo "  Allowing $envrc"
    direnv allow "$(dirname "$envrc")"
done

# Export environment initialization to persist for subsequent bash commands
cat >> "$CLAUDE_ENV_FILE" << 'EOF'
# Nix profile
if [ -f ~/.nix-profile/etc/profile.d/nix.sh ]; then
    . ~/.nix-profile/etc/profile.d/nix.sh
fi

# direnv hook
eval "$(direnv hook bash)"
EOF

echo "Development environment setup complete"
echo "  - Nix: $(nix --version | head -1)"
echo "  - devenv: $(devenv version)"
echo "  - direnv: $(direnv version)"
