#!/bin/bash
# Render the claude-quota extension panel/menu to a PNG.
#
# Usage:
#   render.sh <fixture-json> <output-png>
#
# Assumes:
#   - The extension is mounted at
#     /usr/share/gnome-shell/extensions/claude-quota@allegedly.works
#   - Output PNG dir is writable.
#
# Env (optional):
#   RENDER_WIDTH, RENDER_HEIGHT — screenshot crop dims (default 1920x40).
set -euo pipefail

FIXTURE="${1:?fixture path required}"
OUT_PNG="${2:?output PNG path required}"
WIDTH="${RENDER_WIDTH:-1920}"
HEIGHT="${RENDER_HEIGHT:-40}"

# rules_distroless does not run dpkg postinst, so the gsettings schemas,
# gdk-pixbuf loader cache, and MIME database are extracted but never
# compiled/built. Do those one-shots now (idempotent).
glib-compile-schemas /usr/share/glib-2.0/schemas/
update-mime-database /usr/share/mime
# libgdk-pixbuf2.0-bin installs the binary under the lib dir; rules_distroless
# skips the update-alternatives postinst that would symlink it onto PATH.
/usr/lib/x86_64-linux-gnu/gdk-pixbuf-2.0/gdk-pixbuf-query-loaders --update-cache

mkdir -p /var/lib/dbus
dbus-uuidgen --ensure=/var/lib/dbus/machine-id

# Tell the extension to load fixture state instead of doing real HTTP.
export CLAUDE_QUOTA_FIXTURE="$FIXTURE"

# Headless X display. Pin depth=24 for byte-identical PNG output.
Xvfb :99 -screen 0 "${WIDTH}x${HEIGHT}x24" -nolisten tcp >/tmp/xvfb.log 2>&1 &
XVFB_PID=$!
trap 'kill $XVFB_PID 2>/dev/null || true' EXIT
export DISPLAY=:99
# Give Xvfb a moment to bind the display socket.
for _ in $(seq 1 20); do
  if xdpyinfo -display :99 >/dev/null 2>&1; then break; fi
  sleep 0.1
done

export UUID="claude-quota@allegedly.works"
export WIDTH HEIGHT OUT_PNG
dbus-run-session -- bash -c '
set -euo pipefail

# accountsservice (called from endSessionDialog at gnome-shell startup)
# treats a missing system D-Bus as fatal. We do not want to stand up a
# real privileged system bus (postinst-created messagebus user is not
# present in rules_distroless extractions). Point the system bus address
# at the session bus instead — connections succeed, services are absent,
# accountsservice degrades to "no user info" instead of crashing the shell.
export DBUS_SYSTEM_BUS_ADDRESS="$DBUS_SESSION_BUS_ADDRESS"

# Force the user-extensions kill switch off and pre-enable the extension
# so gnome-shell loads it on first paint.
gsettings set org.gnome.shell disable-user-extensions false
gsettings set org.gnome.shell enabled-extensions "[\"$UUID\"]"

gnome-shell --x11 >/tmp/shell.log 2>&1 &
SHELL_PID=$!

# Wait for the shell to own its bus name. The shell fork-execs subprocesses
# during startup (ibus, etc.) and may take several seconds in a cold
# container.
for i in $(seq 1 120); do
  if gdbus introspect --session --dest org.gnome.Shell \
        --object-path /org/gnome/Shell >/dev/null 2>&1; then
    echo "shell ready after ${i}*0.5s"
    break
  fi
  if ! kill -0 "$SHELL_PID" 2>/dev/null; then
    echo "gnome-shell exited before becoming ready; last log:" >&2
    tail -50 /tmp/shell.log >&2
    exit 1
  fi
  sleep 0.5
done

# Wait for the extension to be loaded by gnome-shell. enabled-extensions
# was set before launch, so this just confirms the shell finished loading.
for i in $(seq 1 40); do
  loaded=$(gdbus call --session --dest org.gnome.Shell \
    --object-path /org/gnome/Shell --method org.gnome.Shell.Extensions.GetExtensionInfo \
    "$UUID" 2>/dev/null | grep -o "'\''state'\'': <2.0>" || true)
  if [[ -n "$loaded" ]]; then
    echo "extension active after ${i}*0.25s"
    break
  fi
  sleep 0.25
done

# Let the panel layout settle (icons, font load, first paint).
sleep 1

# ImageMagick grab — the GNOME Shell.Screenshot D-Bus interface is gated
# on unsafe_mode in modern GNOME and external callers get AccessDenied.
# Xvfb is sized to exactly the panel area, so the X root window IS the
# panel.
scrot --display :99 --overwrite "$OUT_PNG"

kill "$SHELL_PID" 2>/dev/null || true
wait "$SHELL_PID" 2>/dev/null || true
'
