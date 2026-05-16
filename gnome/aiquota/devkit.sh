#!/bin/bash
# Bazel-runnable launcher for local iteration on aiquota.
#
# Builds the extension zip via Bazel, installs it into the user's
# gnome-shell extension dir (replacing any previous build), and launches
# a nested gnome-shell --devkit session with the extension pre-enabled.
# Requires gnome-shell to be installed on the host (not bundled — local
# iteration only).
#
# Usage:
#   bazelisk run //gnome/aiquota:devkit
#
# Optional env:
#   AI_QUOTA_FIXTURE=/path/to/fixture.json
#       Skip real auth/HTTP and load the indicator from a fixture JSON
#       (same hook used by //gnome/aiquota:test_render).
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
zip_path="$(rlocation "_main/gnome/aiquota/aiquota.zip")"
if [[ ! -f "$zip_path" ]]; then
  echo "ERROR: aiquota.zip not found in runfiles at $zip_path" >&2
  exit 1
fi

uuid="aiquota@allegedly.works"
target_dir="${HOME}/.local/share/gnome-shell/extensions/${uuid}"

# --- extract to temp dir (avoids polluting ~/.local/share) -----------------
tmpdir=$(mktemp -d "${TMPDIR:-/tmp}/aiquota-devkit.XXXXXX")
ext_dir="$tmpdir/gnome-shell/extensions/$uuid"
mkdir -p "$ext_dir"
echo ">> extracting $(basename "$zip_path") → $ext_dir"
unzip -q -o "$zip_path" -d "$ext_dir"
trap 'rm -rf "$tmpdir"' EXIT

# --- add temp dir to XDG_DATA_DIRS so gnome-shell discovers the extension --
export XDG_DATA_DIRS="$tmpdir${XDG_DATA_DIRS:+:$XDG_DATA_DIRS}"

# --- enable via gsettings --------------------------------------------------
# Write directly to dconf so the devkit session picks it up.
# `gnome-extensions enable` needs a running shell (DBus), so we use gsettings.
gsettings set org.gnome.shell disable-user-extensions false
current=$(gsettings get org.gnome.shell enabled-extensions 2>/dev/null || echo "@as []")
if echo "$current" | grep -q "'$uuid'"; then
  echo ">> $uuid already in enabled-extensions"
else
  # Append to the existing list without clobbering other extensions.
  gsettings set org.gnome.shell enabled-extensions \
    "$(python3 -c "import ast,sys; l=ast.literal_eval(sys.argv[1]); l.append(sys.argv[2]); print(repr(l))" "$current" "$uuid")"
  echo ">> added $uuid to enabled-extensions"
fi

# --- launch the devkit shell ----------------------------------------------
# --devkit replaces the GNOME 45-removed --nested. Wayland is required;
# the host needs an active Wayland compositor to attach to.
echo ">> launching gnome-shell --devkit (Ctrl-C to exit)"
exec dbus-run-session -- gnome-shell --devkit --wayland
