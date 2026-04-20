#!/bin/sh
# Sync CPAP data from ez Share WiFi SD card to OUTPUT_DIR.
set -eu

NM_CONNECTION=${NM_CONNECTION:-cpap-ezshare}
OUTPUT_DIR=${OUTPUT_DIR:-/data/cpap}

cleanup() {
  nmcli connection down "$NM_CONNECTION" 2>/dev/null || true
}
trap cleanup EXIT

nmcli connection up "$NM_CONNECTION"

mkdir -p "$OUTPUT_DIR"
python3 -m ezshare -w -d / -t "$OUTPUT_DIR" -r
