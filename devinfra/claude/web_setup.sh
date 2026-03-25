#!/bin/bash
# Setup script for Claude Code web sessions.
#
# Installs:
#   1. Nix (official single-user installer with permissive config)
#   2. web-session — claude-hooks, bbapi, gh, skills; from flake via attic binary cache
#   3. skills — symlinked per-skill into ~/.claude/skills/ (preserves Anthropic defaults)
#
# Usage (Claude Code web UI setup command):
#   curl -fsSL https://raw.githubusercontent.com/agentydragon/ducktape/main/devinfra/claude/web_setup.sh | bash
set -euo pipefail

LOG_FILE="/tmp/web-setup.log"
exec > >(tee -a "$LOG_FILE") 2>&1

FLAKE="github:agentydragon/ducktape"

# --- Step 1: Install Nix ---
# Write nix.conf BEFORE the installer runs. The installer internally runs
# `nix-env -i` which reads this config. Without it:
#   - build-users-group defaults to 'nixbld' (group doesn't exist in container)
#   - the install fails immediately
# We allow local builds here because `nix-env -i` builds a trivial
# user-environment.drv (just profile symlinks). Step 2 locks this down.
echo "Pre-configuring Nix for installation..."
mkdir -p ~/.config/nix
cat >~/.config/nix/nix.conf <<'EOF'
build-users-group =
sandbox = false
EOF

echo "Installing Nix..."
# Ensure $USER is set — the installer's nix.sh (sourced below) is a no-op
# when $USER is empty, which means PATH never gets ~/.nix-profile/bin.
# The container runs as root but may not have $USER in the environment.
_saved_user="${USER:-}"
export USER="${USER:-$(id -u -n)}"
curl -fsSL https://nixos.org/nix/install | sh -s -- --no-daemon
# shellcheck disable=SC1091
. ~/.nix-profile/etc/profile.d/nix.sh
# Restore $USER to its original state so we don't leak a side-effect.
if [ -z "$_saved_user" ]; then unset USER; else USER="$_saved_user"; fi
unset _saved_user

# --- Step 2: Lock down Nix for gVisor ---
# max-jobs=0: all real builds come from binary cache, gVisor can't build locally.
# sandbox=false: gVisor already provides isolation; Nix sandboxing would fail.
# Only our attic cache — cache.nixos.org is redundant since CI pre-pushes
# all closures to attic, and the extra cache lookups just slow things down.
echo "Configuring Nix for gVisor..."
cat >~/.config/nix/nix.conf <<'EOF'
build-users-group =
experimental-features = nix-command flakes
sandbox = false
max-jobs = 0
system-features =
substituters = https://cache.allegedly.works/main
trusted-public-keys = cache.allegedly.works-1:OX/cis8G1W13DALkGvhdUZ1OY3yGATbXw8+tIc8J7oA=
EOF

# --- Step 3: Install web session tools (cache hit) ---
# web-session bundles: claude-hooks, bbapi, gh, skills.
# Debug: verify proxy config and connectivity before Nix operations.
# No DNS in the container — all HTTPS goes through CONNECT proxy.
env | sed 's/^\(DUCKTAPE_CLAUDE_HOOKS_K8S_TOKEN=\).*/\1<redacted>/' | sort
echo "Connectivity check (cache.allegedly.works)..."
if ! curl -fsSL --max-time 10 https://cache.allegedly.works/main/nix-cache-info; then
  echo "ERROR: cannot reach cache.allegedly.works through proxy"
  exit 1
fi
echo "Installing web session tools..."
nix profile install "${FLAKE}#web-session"

# --- Step 4: Symlink skills into ~/.claude/skills/ ---
# Per-skill symlinks instead of replacing the directory, so Anthropic's
# pre-landed default skills are preserved.
echo "Deploying skills to ~/.claude/skills/..."
mkdir -p ~/.claude/skills
for skill in ~/.nix-profile/share/claude-hooks/skills/*/; do
  ln -sfn "$skill" ~/.claude/skills/"$(basename "$skill")"
done

echo "Setup complete. Log: ${LOG_FILE}"
