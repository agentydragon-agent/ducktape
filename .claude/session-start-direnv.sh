#!/bin/bash
set -e

[ "$CLAUDE_CODE_REMOTE" != "true" ] && exit 0

echo "Setting up dev environment..." >&2

# Install Nix with sandbox disabled (required for container)
if ! command -v nix &> /dev/null; then
    mkdir -p ~/.config/nix
    cat > ~/.config/nix/nix.conf << 'EOF'
build-users-group =
experimental-features = nix-command flakes
sandbox = false
EOF
    curl -L https://nixos.org/nix/install | sh -s -- --no-daemon 2>&1 | tail -3 >&2 || true

    # Manual profile setup (installer may fail at this step)
    NIX_PKG=$(ls -d /nix/store/*-nix-[0-9]* 2>/dev/null | head -1)
    if [ -n "$NIX_PKG" ]; then
        mkdir -p /nix/var/nix/profiles/per-user/root
        ln -sfn "$NIX_PKG" /nix/var/nix/profiles/per-user/root/profile
        ln -sfn /nix/var/nix/profiles/per-user/root/profile ~/.nix-profile
    fi
fi
[ -d ~/.nix-profile/bin ] && export PATH="$HOME/.nix-profile/bin:$PATH"

# Install direnv
if ! command -v direnv &> /dev/null; then
    curl -sfL "https://github.com/direnv/direnv/releases/download/v2.35.0/direnv.linux-amd64" -o /usr/local/bin/direnv
    chmod +x /usr/local/bin/direnv
fi

# Allow .envrc files
if [ -n "$CLAUDE_PROJECT_DIR" ]; then
    cd "$CLAUDE_PROJECT_DIR"
    find . -name ".envrc" -type f 2>/dev/null | while read f; do
        direnv allow "$(dirname "$f")" 2>/dev/null || true
    done
fi

# Output direnv hook for bash
cat << 'EOF'
# direnv hook for .envrc activation
if command -v direnv &> /dev/null; then
    eval "$(direnv hook bash)"
fi
EOF

echo "Setup complete: nix=$(nix --version 2>/dev/null || echo 'N/A'), direnv=$(direnv version 2>/dev/null || echo 'N/A')" >&2
