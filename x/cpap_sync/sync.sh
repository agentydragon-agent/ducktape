#!/bin/sh
# Sync CPAP data from ez Share WiFi SD card to OUTPUT_DIR.
set -eu

IFACE=${WIFI_IFACE:-wlx9cefd5f62ee0}
SSID=${WIFI_SSID:-"Rai CPAP ez Share"}
OUTPUT_DIR=${OUTPUT_DIR:-/data/cpap}

WPA_CONF=$(mktemp /tmp/ezshare-wpa-XXXXXX.conf)
printf 'network={\n    ssid="%s"\n    psk="%s"\n    key_mgmt=WPA-PSK\n}\n' \
  "$SSID" "$WIFI_PASSWORD" >"$WPA_CONF"

cleanup() {
  dhclient -r "$IFACE" 2>/dev/null || true
  kill "$(cat /tmp/ezshare-wpa.pid 2>/dev/null)" 2>/dev/null || true
  ip link set "$IFACE" down 2>/dev/null || true
  rm -f "$WPA_CONF"
}
trap cleanup EXIT

ip link set "$IFACE" up
wpa_supplicant -B -i "$IFACE" -c "$WPA_CONF" -P /tmp/ezshare-wpa.pid
dhclient -1 -d --no-pid "$IFACE"
ip route del default dev "$IFACE" 2>/dev/null || true

mkdir -p "$OUTPUT_DIR"
python3 -m ezshare -w -d / -t "$OUTPUT_DIR" -r
