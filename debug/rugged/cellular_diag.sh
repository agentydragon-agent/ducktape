#!/usr/bin/env bash
# Full cellular bring-up + diagnostic + auto-recovery.
#
# Defaults: keeps WiFi up. All cellular diagnostics bind to wwan0 explicitly
# (`curl --interface wwan0`, `ping -I wwan0`) so WiFi can stay the default
# route during the test. Set KILL_WIFI=1 to additionally exercise the
# WiFi-down failover path.
#
# What it does, in order:
#   1. Snapshot pre-state (routes, NM, mmcli, mbim) to OUT/.
#   2. Stop ModemManager, switch slot mapping to physical SIM (slot 1 = mbim 0),
#      restart MM, wait for re-probe.
#   3. (KILL_WIFI=1 only) Turn WiFi radio OFF.
#   4. Bring modem online: lock to LTE, `nmcli connection up "Google Fi"`.
#      FCC unlock is handled by the wired fcc-unlock.d/105b:e11d (MM invokes
#      it on "software radio switch is OFF") and the foxflss-watchdog
#      service as a backstop.
#   5. Run diagnostics: signal, MBIM register/packet/connection state, ICMP
#      ping, HTTP/HTTPS throughput, the TCP-RTT-vs-ICMP smoking-gun test.
#      DNS only when KILL_WIFI=1 (otherwise resolver goes via WiFi default).
#   6. Dump full unfiltered ModemManager / NetworkManager / kernel journal +
#      full mmcli + mbim dumps to OUT/.
#   7. RECOVERY (always — wired via EXIT trap, fires even on Ctrl+C / errors):
#        - tear down "Google Fi"
#        - (KILL_WIFI=1 only) turn WiFi back on, wait for reconnect
#        - print final routes + NM device status

set -uo pipefail
[ "$(id -u)" -eq 0 ] || {
  echo "must run as root" >&2
  exit 1
}

REPO=/home/agentydragon/code/ducktape
TS=$(date +%Y%m%d-%H%M%S)
OUT="$REPO/debug/rugged-mobile-net-diag/$TS"
mkdir -p "$OUT"
exec > >(tee -a "$OUT/00-script.log") 2>&1

START_EPOCH=$(date +%s)
START_HUMAN=$(date '+%Y-%m-%d %H:%M:%S')
KILL_WIFI=${KILL_WIFI:-0}
WIFI_DEV=wlp0s20f3
WIFI_CONN=Howleroi
GSM_CONN="Google Fi"
MBIM_DEV=/dev/wwan0mbim0

say() { printf '\n========== %s ==========\n' "$*"; }
hdr() { printf '\n----- %s -----\n' "$*"; }
modem_id() { mmcli -L 2>/dev/null | grep -oE '/Modem/[0-9]+' | head -1 | sed 's:/Modem/::'; }
modem_state() {
  mmcli -m "${1:-$MID}" -K 2>/dev/null \
    | awk -F: '/^modem\.generic\.state[[:space:]]/{gsub(/^[[:space:]]+|[[:space:]]+$/,"",$2); print $2}'
}
sim_id() {
  mmcli -m "${1:-$MID}" 2>/dev/null \
    | grep 'primary sim path' \
    | grep -oE '/SIM/[0-9]+' \
    | head -1 \
    | sed 's:/SIM/::'
}

# ─────────────────────────── recovery trap ────────────────────────────────
recover() {
  local rc=$?
  say "RECOVERY (script exit=$rc)"
  hdr "tear down cellular"
  nmcli connection down "$GSM_CONN" 2>&1 || true
  if [ "$KILL_WIFI" = 1 ]; then
    hdr "turn WiFi radio back on"
    nmcli radio wifi on 2>&1 || true
    hdr "wait up to 45s for WiFi reconnect"
    for i in $(seq 1 45); do
      state=$(nmcli -t -f DEVICE,STATE device 2>/dev/null \
        | awk -F: -v d="$WIFI_DEV" '$1==d{print $2}')
      printf '  [%2ds] wifi state=%s\n' "$i" "$state"
      [ "$state" = "connected" ] && break
      sleep 1
    done
  fi
  hdr "post-recovery routes"
  ip -4 route 2>&1 || true
  echo
  ip -6 route 2>&1 | head -10 || true
  hdr "post-recovery NM device status"
  nmcli device status 2>&1 || true
  hdr "DONE"
  echo "Outputs: $OUT"
  exit "$rc"
}
trap recover EXIT

# ─────────────────────────── PHASE 1: pre-state ───────────────────────────
say "PHASE 1 — pre-state snapshot ($START_HUMAN)"
hdr "uname / date"
uname -a
date
hdr "ip addr"
ip addr
hdr "ip -4 route"
ip -4 route
hdr "ip -6 route"
ip -6 route
hdr "ip rule"
ip rule
hdr "nmcli device status"
nmcli device status
hdr "nmcli connection show"
nmcli connection show
hdr "nmcli radio"
nmcli radio
hdr "rfkill list"
rfkill list
hdr "mmcli -L"
mmcli -L
MID=$(modem_id)
echo "modem id: ${MID:-<none>}"
if [ -n "${MID:-}" ]; then
  hdr "mmcli -m $MID (initial)"
  mmcli -m "$MID" || true
  PRE_SIM=$(sim_id)
  if [ -n "$PRE_SIM" ]; then
    hdr "mmcli -i $PRE_SIM (initial active SIM)"
    mmcli -i "$PRE_SIM" || true
  fi
  for s in 9 7; do
    hdr "mmcli -i $s"
    mmcli -i "$s" 2>&1 || true
  done
fi
hdr "mbim slot mappings (before, via -p proxy)"
mbimcli -d "$MBIM_DEV" -p --ms-query-device-slot-mappings 2>&1 || true
hdr "mbim slot 0 info (before)"
mbimcli -d "$MBIM_DEV" -p --ms-query-slot-info-status=0 2>&1 || true
hdr "mbim slot 1 info (before)"
mbimcli -d "$MBIM_DEV" -p --ms-query-slot-info-status=1 2>&1 || true

# ─────────────────────────── PHASE 2: switch slot ─────────────────────────
say "PHASE 2 — switch slot mapping to physical SIM (mbim mapping=0 / slot 1)"
hdr "stop ModemManager"
systemctl stop ModemManager
sleep 2
hdr "set slot mapping = 0 (physical)"
mbimcli -d "$MBIM_DEV" --ms-set-device-slot-mappings=0 2>&1 || true
sleep 2
hdr "start ModemManager"
systemctl start ModemManager
hdr "wait up to 90s for re-probe"
MID=""
for i in $(seq 1 90); do
  cand=$(modem_id)
  if [ -n "$cand" ]; then
    if mmcli -m "$cand" 2>/dev/null | grep -q -E '(iccid|state:)'; then
      MID="$cand"
      printf '  [%2ds] re-probed: modem id=%s\n' "$i" "$MID"
      break
    fi
  fi
  sleep 1
done
[ -n "$MID" ] || {
  echo "modem never re-probed; aborting"
  exit 1
}

hdr "mmcli -m $MID (after slot switch)"
mmcli -m "$MID" || true
ACTIVE_SIM=$(sim_id)
if [ -n "$ACTIVE_SIM" ]; then
  hdr "mmcli -i $ACTIVE_SIM (active SIM after switch)"
  mmcli -i "$ACTIVE_SIM" || true
fi
hdr "mbim slot mappings (after)"
mbimcli -d "$MBIM_DEV" -p --ms-query-device-slot-mappings 2>&1 || true

# ─────────────────────────── PHASE 3: WiFi off (optional) ────────────────
if [ "$KILL_WIFI" = 1 ]; then
  say "PHASE 3 — turn WiFi off (KILL_WIFI=1)"
  hdr "wifi state before"
  nmcli -t -f DEVICE,STATE,CONNECTION device | grep -E "$WIFI_DEV|wifi"
  nmcli radio wifi off
  sleep 4
  hdr "wifi state after"
  nmcli -t -f DEVICE,STATE,CONNECTION device | grep -E "$WIFI_DEV|wifi"
  hdr "rfkill"
  rfkill list
  hdr "current default routes (should be empty or wwan-only)"
  ip -4 route show default
  ip -6 route show default
else
  say "PHASE 3 — skipped (KILL_WIFI=0; WiFi stays up, cellular tests bind to wwan0)"
fi

# ─────────────────────────── PHASE 4: modem online ────────────────────────
say "PHASE 4 — bring modem online"

# FCC unlock is handled out-of-band by:
#   - MM's wired fcc-unlock.d/105b:e11d (fires when MM detects "Cannot power-up:
#     software radio switch is OFF"), and
#   - foxflss-watchdog.service (fires after 12 s if MM gets stuck).
# This loop just waits up to 90 s for one of them to land us in registered.
hdr "wait up to 90s for registration / enabled / connected"
for i in $(seq 1 90); do
  MID=$(modem_id)
  state=$(modem_state "$MID")
  printf '  [%2ds] modem=%s state=%s\n' "$i" "${MID:-?}" "${state:-?}"
  case "$state" in
    registered | enabled | connected | connecting) break ;;
  esac
  sleep 1
done

hdr "lock to LTE only (5G NR unusable at primary location)"
mmcli -m "$MID" --set-allowed-modes=4g 2>&1 || true
sleep 3

hdr "bring up '$GSM_CONN' connection"
nmcli connection up "$GSM_CONN" 2>&1 || true
sleep 5

hdr "modem state after connect attempt"
mmcli -m "$MID" || true
hdr "bearer info"
BPATH=$(mmcli -m "$MID" 2>/dev/null | grep -oE '/Bearer/[0-9]+' | head -1)
if [ -n "$BPATH" ]; then mmcli -b "${BPATH#/Bearer/}" 2>&1 || true; else echo "no bearer"; fi
hdr "wwan0 addr"
ip addr show wwan0 2>&1 || true
hdr "v4 routes (cellular phase)"
ip -4 route
hdr "v6 routes (cellular phase)"
ip -6 route

# ─────────────────────────── PHASE 5: diagnostics ─────────────────────────
say "PHASE 5 — diagnostics"

hdr "signal (extended, after 5s setup)"
mmcli -m "$MID" --signal-setup=5 2>&1 || true
sleep 6
mmcli -m "$MID" --signal-get 2>&1 || true

hdr "mbim signal state"
mbimcli -d "$MBIM_DEV" -p --query-signal-state 2>&1 || true
hdr "mbim register state"
mbimcli -d "$MBIM_DEV" -p --query-register-state 2>&1 || true
hdr "mbim packet service state"
mbimcli -d "$MBIM_DEV" -p --query-packet-service-state 2>&1 || true
hdr "mbim connection state (session 0)"
mbimcli -d "$MBIM_DEV" -p --query-connection-state=0 2>&1 || true
hdr "mbim subscriber ready status"
mbimcli -d "$MBIM_DEV" -p --query-subscriber-ready-status 2>&1 || true
hdr "mbim home provider"
mbimcli -d "$MBIM_DEV" -p --query-home-provider 2>&1 || true

hdr "ICMP ping 8.8.8.8 via wwan0"
ping -I wwan0 -c 5 -W 3 8.8.8.8 2>&1 || true
hdr "ICMP ping 1.1.1.1 via wwan0"
ping -I wwan0 -c 5 -W 3 1.1.1.1 2>&1 || true

hdr "DNS lookup (dig @8.8.8.8 google.com, bound to wwan0 source IP)"
WWAN_IP=$(ip -4 -o addr show wwan0 2>/dev/null | awk '{print $4}' | cut -d/ -f1)
if [ -n "$WWAN_IP" ]; then
  dig @8.8.8.8 -b "$WWAN_IP" +tries=1 +time=3 google.com 2>&1 || true
else
  echo "no wwan0 IPv4 — skipping DNS test"
fi

hdr "HTTP throughput — Tele2 1MB"
curl --interface wwan0 -4 -o /dev/null -sm 30 \
  -w "speed: %{speed_download} B/s  time: %{time_total}s  http: %{http_code}\n" \
  http://speedtest.tele2.net/1MB.zip 2>&1 || true
hdr "HTTPS throughput — Tele2 1MB (with -v on failure for diagnosis)"
curl --interface wwan0 -4 -o /dev/null -sm 30 \
  -w "speed: %{speed_download} B/s  time: %{time_total}s  http: %{http_code}\n" \
  https://speedtest.tele2.net/1MB.zip 2>&1 || true
# If the above failed (http=000 commonly seen), capture verbose output once
# to surface whether it's TLS handshake / TCP connect / DNS / route.
echo "--- HTTPS verbose probe (single connect, 8s cap) ---"
curl --interface wwan0 -4 -v -o /dev/null -sm 8 \
  https://speedtest.tele2.net/1MB.zip 2>&1 \
  | grep -E '^(\*|< HTTP)' | head -20 || true

hdr "SMOKING GUN — TCP RTT vs ICMP RTT during 10MB transfer"
WWAN_IP=$(ip -4 -o addr show wwan0 2>/dev/null | awk '{print $4}' | cut -d/ -f1)
echo "wwan0 source IP: ${WWAN_IP:-<none>}"
(curl --interface wwan0 -4 -o /dev/null -sm 25 \
  http://speedtest.tele2.net/10MB.zip >/dev/null 2>&1) &
CURL_PID=$!
sleep 3
echo "--- ss -tnei src $WWAN_IP (cellular sockets only) ---"
[ -n "$WWAN_IP" ] && ss -tnei src "$WWAN_IP" 2>&1 || echo "no wwan0 IP"
echo "--- ICMP ping during transfer (5x at 0.5s interval) ---"
ping -I wwan0 -c 5 -W 3 -i 0.5 8.8.8.8 2>&1 || true
wait $CURL_PID 2>/dev/null || true

hdr "Final 10MB throughput"
curl --interface wwan0 -4 -o /dev/null -sm 60 \
  -w "speed: %{speed_download} B/s  time: %{time_total}s  http: %{http_code}\n" \
  http://speedtest.tele2.net/10MB.zip 2>&1 || true

hdr "10MB HTTPS throughput"
curl --interface wwan0 -4 -o /dev/null -sm 60 \
  -w "speed: %{speed_download} B/s  time: %{time_total}s  http: %{http_code}\n" \
  https://speedtest.tele2.net/10MB.zip 2>&1 || true

hdr "Path MTU probe (DF-bit ping at 1200, 1300, 1400, 1500)"
for size in 1172 1272 1372 1472; do
  echo "--- payload=$size (IP=$((size + 28))) ---"
  ping -I wwan0 -M do -c 3 -W 2 -s "$size" 8.8.8.8 2>&1 || true
done

hdr "operator info / location-status"
mmcli -m "$MID" --location-status 2>&1 || true

# ─────────────────────────── PHASE 6: collect logs ────────────────────────
say "PHASE 6 — collect full unfiltered logs to $OUT"
journalctl -u ModemManager --since "@$START_EPOCH" --no-pager >"$OUT/01-mm.log" 2>&1
journalctl -u NetworkManager --since "@$START_EPOCH" --no-pager >"$OUT/02-nm.log" 2>&1
journalctl -k --since "@$START_EPOCH" --no-pager >"$OUT/03-kernel.log" 2>&1
journalctl --since "@$START_EPOCH" --no-pager >"$OUT/04-journal-all.log" 2>&1

mmcli -L >"$OUT/10-mmcli-list.txt" 2>&1
mmcli -m "$MID" >"$OUT/11-mmcli-modem.txt" 2>&1 || true
ACTIVE_SIM=$(sim_id)
[ -n "$ACTIVE_SIM" ] && mmcli -i "$ACTIVE_SIM" >"$OUT/12-mmcli-sim.txt" 2>&1 || true
[ -n "$BPATH" ] && mmcli -b "${BPATH#/Bearer/}" >"$OUT/13-mmcli-bearer.txt" 2>&1 || true

{
  for q in --query-device-caps --ms-query-device-slot-mappings \
    '--ms-query-slot-info-status=0' '--ms-query-slot-info-status=1' \
    --query-signal-state --query-register-state \
    --query-packet-service-state '--query-connection-state=0' \
    --query-subscriber-ready-status --query-home-provider \
    --query-radio-state --query-pin-state; do
    echo "=== mbimcli $q ==="
    eval mbimcli -d "$MBIM_DEV" -p $q 2>&1
    echo
  done
} >"$OUT/20-mbim.txt" 2>&1

{
  echo "=== ip addr ==="
  ip addr
  echo
  echo "=== ip -4 route ==="
  ip -4 route
  echo
  echo "=== ip -6 route ==="
  ip -6 route
  echo
  echo "=== ip rule ==="
  ip rule
  echo
  echo "=== ss -s ==="
  ss -s
  echo
  echo "=== ss -tnei (all) ==="
  ss -tnei
} >"$OUT/30-ip.txt" 2>&1

{
  echo "=== nmcli device status ==="
  nmcli device status
  echo
  echo "=== nmcli connection show ==="
  nmcli connection show
  echo
  echo "=== nmcli connection show '$GSM_CONN' ==="
  nmcli connection show "$GSM_CONN"
  echo
  echo "=== nmcli connection show '$WIFI_CONN' ==="
  nmcli connection show "$WIFI_CONN"
} >"$OUT/40-nmcli.txt" 2>&1

say "PHASE 7 — handing off to recovery trap (EXIT)"
echo "Outputs: $OUT"
ls -la "$OUT"
