#!/usr/bin/env bash
# Provision a new eSIM profile on the Foxconn DW5934e modem.
#
# Commands:
#   sudo ./esim-provision.sh wipe
#   sudo ./esim-provision.sh activate /path/to/qr-code.png
#   sudo ./esim-provision.sh activate "LPA:1$smdp$matching-id"
#   sudo ./esim-provision.sh status
#
# "wipe" deletes all profiles and verifies the eUICC is empty.
# "activate" wipes, downloads a new profile, and brings the modem online.
# "status" shows current eUICC and modem state without changing anything.
#
# Each step is verified before proceeding to the next.
#
# Requires: lpac, mbimcli, zbarimg, FoxFlss, mmcli (all in NixOS config)
# Must run as root.

set -euo pipefail

PCI_ADDR="0000:71:00.0"
MHI_DRIVER="/sys/bus/pci/drivers/mhi-pci-generic"
MBIM_DEV="/dev/wwan0mbim0"

die() {
  echo "FATAL: $*" >&2
  exit 1
}

log() { echo "=== $* ==="; }
step() { echo "  $*"; }

[ "$(id -u)" -eq 0 ] || die "must run as root"
[ $# -ge 1 ] || die "usage: $0 <wipe|activate|status> [qr-image.png | LPA string]"

# ── Helpers ──────────────────────────────────────────────────────────────────

lpac_run() {
  LPAC_APDU=mbim \
    LPAC_APDU_MBIM_DEVICE="$MBIM_DEV" \
    LPAC_APDU_MBIM_UIM_SLOT=2 \
    lpac "$@"
}

mhi_rebind() {
  step "MHI rebind..."
  echo "$PCI_ADDR" >"$MHI_DRIVER/unbind" 2>/dev/null || true
  sleep 3
  echo "$PCI_ADDR" >"$MHI_DRIVER/bind" 2>/dev/null || true
  sleep 8
  step "MHI rebind done."
}

# Verify eUICC is accessible via lpac. Returns 0 if yes.
verify_lpac_access() {
  lpac_run chip info >/dev/null 2>&1
}

# Verify eUICC has no profiles. Dies if profiles remain.
verify_empty() {
  log "Verifying eUICC is empty"

  # Primary check: mbimcli application list. An empty eUICC has no
  # USIM/ISIM apps. If apps are present, a profile is still active.
  step "Checking UICC application list (mbimcli)..."
  local APP_LIST
  APP_LIST=$(mbimcli -d "$MBIM_DEV" --ms-query-uicc-application-list 2>&1 || true)
  if echo "$APP_LIST" | grep -qi 'usim\|isim'; then
    echo "$APP_LIST"
    die "eUICC still has active applications — wipe incomplete"
  fi
  step "No USIM/ISIM applications — eUICC is empty."

  # Secondary check: lpac profile list (may fail with SelectFailed on
  # empty eUICC, which is fine — it confirms no profiles).
  step "Checking lpac profile list..."
  local LIST_OUT
  LIST_OUT=$(lpac_run profile list 2>&1 || true)
  if echo "$LIST_OUT" | grep -q '"iccid"'; then
    echo "$LIST_OUT"
    die "lpac still sees profiles on eUICC — wipe incomplete"
  fi
  step "Verified: eUICC is clean."
}

# Verify a profile is active. Dies if not.
verify_profile_active() {
  log "Verifying profile is active"

  step "Checking UICC application list (mbimcli)..."
  local APP_LIST
  APP_LIST=$(mbimcli -d "$MBIM_DEV" --ms-query-uicc-application-list 2>&1 || true)
  if echo "$APP_LIST" | grep -qi 'usim'; then
    step "USIM application present — profile is active."
    echo "$APP_LIST" | grep -i 'application'
  else
    echo "$APP_LIST"
    die "no USIM application found — profile may not be enabled"
  fi
}

# Bring modem from failed/low to connected. No reboot needed.
bring_modem_online() {
  log "Bringing modem online"

  step "MHI rebind..."
  mhi_rebind

  step "Starting ModemManager (for mbim-proxy)..."
  systemctl start ModemManager
  sleep 10

  step "FCC unlock (FoxFlss)..."
  FoxFlss 2>&1 || step "FoxFlss returned non-zero (may be OK if already unlocked)"
  sleep 5

  step "Restarting ModemManager..."
  systemctl restart ModemManager
  sleep 15

  local MODEM_ID
  MODEM_ID=$(mmcli -L 2>/dev/null | grep -oP '/Modem/\K[0-9]+' | head -1 || true)
  if [ -z "$MODEM_ID" ]; then
    die "ModemManager did not detect modem after restart"
  fi

  local STATE
  STATE=$(mmcli -m "$MODEM_ID" 2>&1 | grep -oP 'state: \K\S+' || true)
  step "Modem state: $STATE"

  if [ "$STATE" != "connected" ] && [ "$STATE" != "registered" ]; then
    mmcli -m "$MODEM_ID" 2>&1 | grep -E 'state:|power|signal|operator'
    die "modem not in connected/registered state"
  fi

  mmcli -m "$MODEM_ID" 2>&1 | grep -E 'state:|power|signal|access|operator'

  local SIM_ID
  SIM_ID=$(mmcli -m "$MODEM_ID" 2>/dev/null | grep -oP '/SIM/\K[0-9]+' | head -1 || true)
  if [ -n "$SIM_ID" ]; then
    echo ""
    step "SIM identity:"
    mmcli -i "$SIM_ID" 2>&1 | grep -E 'iccid|imsi|operator'
  fi
}

# ── Wipe ─────────────────────────────────────────────────────────────────────

do_wipe() {
  # MM must have run at least once to initialize the modem's MBIM stack.
  # Start it (may fail with esim-without-profiles — that's fine), then stop.
  log "Initializing modem MBIM stack"
  systemctl start ModemManager 2>/dev/null || true
  sleep 8
  systemctl stop ModemManager 2>/dev/null || true
  sleep 2

  log "Resetting modem (MHI rebind)"
  mhi_rebind

  if ! verify_lpac_access; then
    step "lpac can't access eUICC — MHI rebind again with longer wait..."
    echo "$PCI_ADDR" >"$MHI_DRIVER/unbind" 2>/dev/null || true
    sleep 5
    echo "$PCI_ADDR" >"$MHI_DRIVER/bind" 2>/dev/null || true
    sleep 15
    verify_lpac_access || die "cannot access eUICC after two MHI rebinds"
  fi

  log "Listing existing profiles"
  local PROFILE_JSON
  PROFILE_JSON=$(lpac_run profile list 2>&1)
  echo "$PROFILE_JSON"

  local ICCIDS
  ICCIDS=$(echo "$PROFILE_JSON" | grep -oP '"iccid":"[^"]+"' | cut -d'"' -f4 || true)

  if [ -z "$ICCIDS" ]; then
    step "No profiles found — eUICC is already clean."
    verify_empty
    return 0
  fi

  log "Deleting all profiles"
  for ICCID in $ICCIDS; do
    local STATE
    STATE=$(echo "$PROFILE_JSON" | grep -oP "\"iccid\":\"$ICCID\"[^}]*\"profileState\":\"[^\"]+\"" \
      | grep -oP '"profileState":"[^"]+"' | cut -d'"' -f4)
    step "Profile $ICCID ($STATE)"

    if [ "$STATE" = "enabled" ]; then
      step "  Disabling..."
      local RESULT
      RESULT=$(lpac_run profile disable "$ICCID" 2>&1)
      if echo "$RESULT" | grep -q '"code":0'; then
        step "  Disabled."
      else
        step "  Disable output: $RESULT"
      fi
      step "  MHI rebind (SIM reset after disable)..."
      mhi_rebind
    fi

    step "  Deleting..."
    local RESULT
    RESULT=$(lpac_run profile delete "$ICCID" 2>&1)
    if echo "$RESULT" | grep -q '"code":0'; then
      step "  Deleted."
    else
      step "  Delete failed, MHI rebind and retry..."
      mhi_rebind
      RESULT=$(lpac_run profile delete "$ICCID" 2>&1)
      if echo "$RESULT" | grep -q '"code":0'; then
        step "  Deleted (after retry)."
      else
        die "could not delete profile $ICCID: $RESULT"
      fi
    fi
  done

  # Verify wipe — need MHI rebind since last delete broke channel
  mhi_rebind
  verify_empty
}

# ── Activate ─────────────────────────────────────────────────────────────────

do_activate() {
  local SMDP="$1" MATCH="$2"

  # Wipe first
  do_wipe

  echo ""
  log "Downloading new profile"
  step "SM-DP+: $SMDP"
  step "This takes 30-60s..."

  # MHI rebind to get clean channel for download
  mhi_rebind

  local DOWNLOAD_OUTPUT
  DOWNLOAD_OUTPUT=$(lpac_run profile download -s "$SMDP" -m "$MATCH" 2>&1)
  echo "$DOWNLOAD_OUTPUT"

  if echo "$DOWNLOAD_OUTPUT" | grep -q '"code":0.*"message":"success"'; then
    step "Download succeeded."
  elif echo "$DOWNLOAD_OUTPUT" | grep -q 'iccid_already_exists_on_euicc'; then
    step "Profile already installed (previous attempt succeeded)."
  elif echo "$DOWNLOAD_OUTPUT" | grep -q 'Transaction timed out'; then
    step "Download timed out — checking if profile was partially installed..."
    mhi_rebind
    local APPS
    APPS=$(mbimcli -d "$MBIM_DEV" --ms-query-uicc-application-list 2>&1 || true)
    if echo "$APPS" | grep -qi 'usim'; then
      step "Profile IS installed despite timeout (USIM app present)."
    else
      die "download timed out and no profile found"
    fi
  else
    die "download failed: $DOWNLOAD_OUTPUT"
  fi

  # Verify profile is active.
  # On empty eUICC, downloaded profile auto-enables (no separate enable needed).
  # lpac may show SelectFailed here — that's OK, we use mbimcli to verify.
  echo ""
  mhi_rebind
  verify_profile_active

  # Bring modem online
  echo ""
  bring_modem_online

  # Lock to LTE (5G NR unusable at primary location)
  echo ""
  log "Locking to LTE"
  local MODEM_ID
  MODEM_ID=$(mmcli -L 2>/dev/null | grep -oP '/Modem/\K[0-9]+' | head -1)
  mmcli -m "$MODEM_ID" --set-allowed-modes=4g 2>&1
  sleep 3

  # Connectivity test
  echo ""
  log "Connectivity test"
  for i in $(seq 1 10); do
    if ip -4 addr show wwan0 2>/dev/null | grep -q 'inet '; then
      break
    fi
    step "Waiting for wwan0 IP... ($i)"
    sleep 2
  done

  ip -4 addr show wwan0 2>/dev/null | grep inet || step "No IPv4 on wwan0"

  echo ""
  step "Ping:"
  ping -I wwan0 -c 3 -W 5 8.8.8.8 2>&1 || step "Ping failed"

  echo ""
  step "Throughput:"
  curl --interface wwan0 -4 -o /dev/null -sm 20 \
    -w "  speed: %{speed_download} B/s  size: %{size_download} bytes  time: %{time_total}s\n" \
    http://speedtest.tele2.net/1MB.zip 2>&1 || step "Download timed out"

  echo ""
  log "Done"
  echo "Check Google Fi app — does this device appear?"
  echo "If throughput is still ~7 KB/s, carrier-side activation is incomplete."
}

# ── Status ───────────────────────────────────────────────────────────────────

do_status() {
  log "Modem status"
  local MODEM_ID
  MODEM_ID=$(mmcli -L 2>/dev/null | grep -oP '/Modem/\K[0-9]+' | head -1 || true)
  if [ -n "$MODEM_ID" ]; then
    mmcli -m "$MODEM_ID" 2>&1 | grep -E 'state:|power|signal|access|operator'
    local SIM_ID
    SIM_ID=$(mmcli -m "$MODEM_ID" 2>/dev/null | grep -oP '/SIM/\K[0-9]+' | head -1 || true)
    if [ -n "$SIM_ID" ]; then
      echo ""
      step "SIM:"
      mmcli -i "$SIM_ID" 2>&1 | grep -E 'iccid|imsi|operator'
    fi
  else
    step "No modem detected by ModemManager"
  fi

  echo ""
  log "UICC applications (mbimcli)"
  mbimcli -d "$MBIM_DEV" -p --ms-query-uicc-application-list 2>&1 || step "mbimcli query failed"

  echo ""
  log "eUICC profiles (lpac)"
  step "Stopping ModemManager for lpac access..."
  systemctl stop ModemManager 2>/dev/null || true
  sleep 2
  mhi_rebind
  lpac_run profile list 2>&1 || step "lpac profile list failed"

  step "Restarting ModemManager..."
  # Bring modem back up
  mhi_rebind
  systemctl start ModemManager
  sleep 10
  FoxFlss 2>&1 || true
  sleep 5
  systemctl restart ModemManager
}

# ── Main ─────────────────────────────────────────────────────────────────────

CMD="$1"
shift

case "$CMD" in
  wipe)
    do_wipe
    echo ""
    log "Wipe complete"
    step "eUICC is empty. ModemManager is stopped."
    step "Run '$0 activate <qr.png>' to provision a new profile."
    ;;
  activate)
    [ $# -ge 1 ] || die "usage: $0 activate <qr-image.png | LPA:1\$smdp\$matching-id>"
    INPUT="$1"
    if [[ "$INPUT" == LPA:* ]]; then
      LPA_STRING="$INPUT"
    else
      [ -f "$INPUT" ] || die "file not found: $INPUT"
      command -v zbarimg >/dev/null || die "zbarimg not found (install zbar)"
      LPA_STRING=$(zbarimg --raw "$INPUT" 2>/dev/null) || die "failed to decode QR from $INPUT"
    fi
    [[ "$LPA_STRING" == LPA:1\$* ]] || die "not a valid LPA string: $LPA_STRING"
    SMDP=$(echo "$LPA_STRING" | cut -d'$' -f2)
    MATCH=$(echo "$LPA_STRING" | cut -d'$' -f3)
    echo "SM-DP+:      $SMDP"
    echo "Matching ID: $MATCH"
    echo ""
    do_activate "$SMDP" "$MATCH"
    ;;
  status)
    do_status
    ;;
  *)
    die "unknown command: $CMD (use wipe, activate, or status)"
    ;;
esac
