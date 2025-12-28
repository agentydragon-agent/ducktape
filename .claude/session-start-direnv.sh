#!/bin/bash
set -e

[ "$CLAUDE_CODE_REMOTE" != "true" ] && exit 0

echo "Setting up dev environment..." >&2

# Install Nix with sandbox disabled (required for container)
NIX_CONF="$CLAUDE_PROJECT_DIR/.claude/nix-web.conf"
export NIX_USER_CONF_FILES="$NIX_CONF"

if ! command -v nix &> /dev/null; then
    # Run installer. The nix-env step fails in gVisor containers due to a PTY bug:
    # nix-env opens /dev/ptmx, forks a sandbox process, then reads from the PTY master.
    # gVisor returns EIO on this read (race condition in PTY emulation). No flags can fix
    # this since the PTY is created internally by nix-env for sandbox communication.
    curl -sL https://nixos.org/nix/install -o /tmp/nix-install.sh
    sh /tmp/nix-install.sh --no-daemon --no-channel-add --no-modify-profile </dev/null >&2 || true

    # Manual profile setup when installer's nix-env fails due to gVisor PTY bug.
    #
    # ROOT CAUSE (discovered via strace):
    # Claude Code web runs on gVisor (runsc), not a real Linux kernel. gVisor's PTY
    # emulation has a race condition. When nix-env builds a derivation, it:
    #   1. Opens /dev/ptmx to create a PTY pair (master fd)
    #   2. Forks a child process for the build sandbox
    #   3. Parent immediately calls read() on the PTY master
    #   4. gVisor returns EIO instead of blocking until data arrives
    #
    # WHY NIX USES PTYs (not pipes):
    # Per C99 7.19.3, stdout is fully buffered when connected to a pipe, but line
    # buffered when connected to a terminal. Nix needs real-time build output, so it
    # uses PTYs to trick programs into line-buffered mode. This is fundamental to
    # Nix's architecture - there's no --use-pipes flag.
    #
    # WHY NO INSTALLER FLAGS HELP:
    # - The PTY is created internally by nix-env, not inherited from the shell
    # - --no-daemon, --no-channel-add, </dev/null, <&- all affect different things
    # - sandbox=false in nix.conf disables namespace isolation, not PTY usage
    # - The gVisor bug is in read() returning EIO, not in any Nix configuration
    #
    # WORKAROUND:
    # Skip nix-env entirely. The installer already unpacked Nix to /nix/store.
    # We just symlink the profile manually, bypassing any derivation builds.
    if [ ! -e ~/.nix-profile/bin/nix ] && [ -d /nix/store ]; then
        NIX_PKG=$(ls -d /nix/store/*-nix-[0-9]* 2>/dev/null | head -1)
        if [ -n "$NIX_PKG" ]; then
            mkdir -p /nix/var/nix/profiles/per-user/root
            ln -sfn "$NIX_PKG" /nix/var/nix/profiles/per-user/root/profile
            ln -sfn /nix/var/nix/profiles/per-user/root/profile ~/.nix-profile
        fi
    fi
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
