#!/bin/bash
set -e

[ "$CLAUDE_CODE_REMOTE" != "true" ] && exit 0

echo "Setting up dev environment..." >&2

# Install Nix with sandbox disabled (required for container)
NIX_CONF="$CLAUDE_PROJECT_DIR/.claude/nix-web.conf"
export NIX_USER_CONF_FILES="$NIX_CONF"

if ! command -v nix &> /dev/null; then
    # Run installer non-interactively (</dev/null prevents stdin issues)
    curl -sL https://nixos.org/nix/install -o /tmp/nix-install.sh
    sh /tmp/nix-install.sh --no-daemon --no-channel-add <&- >&2 || true
fi
[ -d ~/.nix-profile/bin ] && export PATH="$HOME/.nix-profile/bin:$PATH"

# Install direnv via nix
if ! command -v direnv &> /dev/null; then
    nix profile install nixpkgs#direnv 2>&1 | tail -3 >&2 || true
fi

# Allow .envrc files
if [ -n "$CLAUDE_PROJECT_DIR" ]; then
    cd "$CLAUDE_PROJECT_DIR"
    find . -name ".envrc" -type f 2>/dev/null | while read f; do
        direnv allow "$(dirname "$f")" 2>/dev/null || true
    done
fi

# Output hooks for bash
cat << EOF
# Nix
export NIX_USER_CONF_FILES="$NIX_CONF"
[ -e ~/.nix-profile/etc/profile.d/nix.sh ] && . ~/.nix-profile/etc/profile.d/nix.sh

# direnv
command -v direnv &>/dev/null && eval "\$(direnv hook bash)"
EOF

echo "Setup complete: nix=$(nix --version 2>/dev/null || echo 'N/A'), direnv=$(direnv version 2>/dev/null || echo 'N/A')" >&2
