#!/bin/bash
# Bazel-runnable launcher for local iteration on claude-quota.
#
# Builds the extension zip via Bazel, installs it into the user's
# gnome-shell extension dir (replacing any previous build), and launches
# a nested gnome-shell --devkit session with the extension pre-enabled.
# Requires gnome-shell to be installed on the host (not bundled — local
# iteration only).
#
# Usage:
#   bazelisk run //gnome/claude_quota:devkit
#
# Optional env:
#   CLAUDE_QUOTA_FIXTURE=/path/to/fixture.json
#       Skip real auth/HTTP and load the indicator from a fixture JSON
#       (same hook used by //gnome/claude_quota:test_render).
set -euo pipefail

# --- begin runfiles.bash initialization v3 ---
# Standard Bazel runfiles bootstrap snippet. `f` must be defined before the
# source chain — set -u rejects unset references in `${RUNFILES_DIR:-/dev/null}/$f`.
f=bazel_tools/tools/bash/runfiles/runfiles.bash
source "${RUNFILES_DIR:-/dev/null}/$f" 2>/dev/null \
  || source "$(grep -sm1 "^$f " "${RUNFILES_MANIFEST_FILE:-/dev/null}" | cut -f2- -d' ')" 2>/dev/null \
  || source "$0.runfiles/$f" 2>/dev/null \
  || source "$(dirname "$0").runfiles/$f" 2>/dev/null \
  || {
    echo >&2 "ERROR: cannot find $f"
    exit 1
  }
# --- end runfiles.bash initialization v3 ---

if ! command -v gnome-shell >/dev/null 2>&1; then
  echo "ERROR: gnome-shell not on PATH. Install it on the host first" >&2
  echo "  (e.g. nix shell nixpkgs#gnome-shell, or use a NixOS GNOME session)." >&2
  exit 1
fi

# --- locate inputs ---------------------------------------------------------
zip_path="$(rlocation "_main/gnome/claude_quota/claude-quota.zip")"
if [[ ! -f "$zip_path" ]]; then
  echo "ERROR: claude-quota.zip not found in runfiles at $zip_path" >&2
  exit 1
fi

uuid="claude-quota@allegedly.works"
target_dir="${HOME}/.local/share/gnome-shell/extensions/${uuid}"

# --- install fresh build ---------------------------------------------------
echo ">> installing $(basename "$zip_path") → $target_dir"
rm -rf "$target_dir"
mkdir -p "$target_dir"
unzip -q -o "$zip_path" -d "$target_dir"

# --- enable via gnome-extensions CLI --------------------------------------
# `gnome-extensions enable` appends to the existing enabled-extensions list.
# Manually rewriting the gsettings key would clobber other extensions the
# user already has on.
gsettings set org.gnome.shell disable-user-extensions false
gnome-extensions enable "$uuid"

# --- launch the devkit shell ----------------------------------------------
# --devkit replaces the GNOME 45-removed --nested. Wayland is required;
# the host needs an active Wayland compositor to attach to.
echo ">> launching gnome-shell --devkit (Ctrl-C to exit)"
exec dbus-run-session -- gnome-shell --devkit --wayland
