#!/usr/bin/env bash
set -euo pipefail

HA_HOST=homeassistant
HA_PACKAGES_DIR=/config/packages/rai
LOCAL_DIR="$(cd "$(dirname "$0")/packages/rai" && pwd)"

echo "=== Diff: local vs HA ==="
changed=$(rsync -avn --out-format="%i %n" "$LOCAL_DIR/" "$HA_HOST:$HA_PACKAGES_DIR/")

if [[ -z "$changed" ]]; then
  echo "No differences — HA is up to date."
  exit 0
fi

echo "$changed"
echo
read -rp "Deploy? [y/N] " answer
if [[ "$answer" =~ ^[Yy]$ ]]; then
  rsync -av "$LOCAL_DIR/" "$HA_HOST:$HA_PACKAGES_DIR/"
  echo "=== Reloading HA ==="
  ssh "$HA_HOST" 'ha core service homeassistant/reload_all'
  echo "Done."
else
  echo "Aborted."
fi
