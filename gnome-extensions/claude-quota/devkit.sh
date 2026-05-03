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
#   bazelisk run //gnome-extensions/claude-quota:devkit
#
# Optional env:
#   CLAUDE_QUOTA_FIXTURE=/path/to/fixture.json
#       Skip real auth/HTTP and load the indicator from a fixture JSON
#       (same hook used by //gnome-extensions/claude-quota:test_render).
set -euo pipefail

# --- runfiles bootstrap (rules_bash convention) ---------------------------
# shellcheck disable=SC1090
source "${RUNFILES_DIR:-/dev/null}/$f" 2>/dev/null \
  || source "$(grep -sm1 "^$f " "${RUNFILES_MANIFEST_FILE:-/dev/null}" | cut -f2- -d' ')" 2>/dev/null \
  || source "$0.runfiles/$f" 2>/dev/null \
  || source "$(dirname "$0").runfiles/$f" 2>/dev/null \
  || {
    echo >&2 "ERROR: cannot find runfiles helper"
    exit 1
  }
# shellcheck disable=SC2154
source "$(rlocation "bazel_tools/tools/bash/runfiles/runfiles.bash")"

if ! command -v gnome-shell >/dev/null 2>&1; then
  echo "ERROR: gnome-shell not on PATH. Install it on the host first" >&2
  echo "  (e.g. nix shell nixpkgs#gnome-shell, or use a NixOS GNOME session)." >&2
  exit 1
fi

# --- locate inputs ---------------------------------------------------------
zip_path="$(rlocation "_main/gnome-extensions/claude-quota/claude-quota.zip")"
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

# --- enable in dconf so devkit shell loads it on first paint ---------------
gsettings set org.gnome.shell disable-user-extensions false
current="$(gsettings get org.gnome.shell enabled-extensions || echo '@as []')"
case "$current" in
  *"$uuid"*) : ;; # already enabled
  *) gsettings set org.gnome.shell enabled-extensions "['${uuid}']" ;;
esac

# --- launch the devkit shell ----------------------------------------------
# --devkit replaces the GNOME 45-removed --nested. Wayland is required;
# the host needs an active Wayland compositor to attach to.
echo ">> launching gnome-shell --devkit (Ctrl-C to exit)"
exec dbus-run-session -- gnome-shell --devkit --wayland
