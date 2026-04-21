# Foxconn DW5932e/DW5934e WWAN modem setup
#
# Initialization: two phases, each triggered differently.
#
# 1. FCC unlock — FoxFlss (bare): allows the software radio to turn on.
#    Wired via ModemManager's fcc-unlock.d; MM calls the script when the modem
#    reports needing FCC unlock. The DW5934e typically boots with power state: on
#    so this may not fire on every boot, but is kept for correctness.
#
# 2. RF calibration — FoxFlss -f Check_RF_SSKU: writes RF tuner settings, DPR
#    tables, and NR carrier aggregation configs from the platform-specific .dat
#    file into the modem's non-volatile storage. Required for full signal quality
#    and 5G NR operation. Idempotent: no-ops if data already matches.
#    Triggered by an NM dispatcher script when wwan0 comes up — at that point
#    the bearer is fully established and MM is in steady state, so FoxFlss can
#    access the MBIM device through mbim-proxy without contention.
#    The .dat files are packaged in the foxflss derivation and symlinked to the
#    path FoxFlss hardcodes (/opt/foxconn/data/) via systemd-tmpfiles.
#
# Hardware: Foxconn DP25-42843-47 (DW5934e, SDX72) — PCI 105b:e11d
# See: debug/rugged/hw/esim.md
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.ducktape.foxconnWwan;

  foxflss = pkgs.callPackage ../../../packages/foxflss.nix { };

  # Script run by the NM dispatcher on wwan0 up: FCC unlock warm-up, then
  # RF calibration. Bare FoxFlss first because on Ubuntu, ModemManager runs
  # fcc-unlock.d (bare FoxFlss) before FoxFlss.service, which flushes stale
  # MBIM CIDs and makes Check_RF_SSKU reliable. Here fcc-unlock.d never fires
  # (modem boots with power state: on), so we replicate that warm-up explicitly.
  foxflssRfCalRun = pkgs.writeShellScript "foxflss-rf-cal-run" ''
    ${foxflss}/bin/FoxFlss && sleep 5 && ${foxflss}/bin/FoxFlss -f Check_RF_SSKU
  '';

  # FCC unlock + RF calibration for ModemManager fcc-unlock.d.
  # Called by MM with: <script> <dbus-path> <port1> [<port2> ...]
  fccUnlockScript = pkgs.writeShellScript "foxconn-dw593xe-fcc-unlock" ''
    [ $# -lt 2 ] && exit 1
    shift  # discard DBus path

    for PORT in "$@"; do
      grep -q MBIM "/sys/class/wwan/$PORT/type" 2>/dev/null && {
        MBIM_PORT=$PORT
        break
      }
      echo "$PORT" | grep -q MBIM && {
        MBIM_PORT=$PORT
        break
      }
    done

    [ -n "$MBIM_PORT" ] || exit 2

    ${foxflss}/bin/FoxFlss
    UNLOCK_RESULT=$?
    if [ $UNLOCK_RESULT -ne 0 ]; then
      echo "Foxconn FCC unlock FAILED" >&2
      exit $UNLOCK_RESULT
    fi

    # RF calibration: write RF tuner/NR-CA/MCFG settings to modem non-volatile
    # storage. Reads /opt/foxconn/data/DW5934e_RF.dat (symlinked via
    # systemd-tmpfiles to the nix store). Idempotent.
    ${foxflss}/bin/FoxFlss -f Check_RF_SSKU
    RF_RESULT=$?
    if [ $RF_RESULT -ne 0 ]; then
      echo "Foxconn RF calibration (Check_RF_SSKU) FAILED: $RF_RESULT" >&2
    fi
    exit $RF_RESULT
  '';
in
{
  options.ducktape.foxconnWwan = {
    enable = lib.mkEnableOption "Foxconn DW5932e/DW5934e WWAN FCC unlock";
  };

  config = lib.mkIf cfg.enable {
    # FCC unlock script for ModemManager
    networking.modemmanager.fccUnlockScripts = [
      {
        id = "105b:e11d";
        path = "${fccUnlockScript}";
      }
    ];

    # Google Fi cellular connection profile.
    # IPv6 never-default: many WiFi networks only provide ULA IPv6 (no default
    # route). Cellular provides global IPv6 with a default route, which causes
    # all IPv6 traffic to silently route over cellular — breaking apps that
    # can't traverse carrier NAT. Disabling the IPv6 default is conservative
    # but safe on all networks. TODO: revisit if true IPv6 failover is needed.
    # IPv4 route-metric 1050: WiFi (metric 600) is preferred when available;
    # cellular is used as failover when WiFi is down.
    networking.networkmanager.ensureProfiles.profiles.google-fi = {
      connection = {
        id = "Google Fi";
        type = "gsm";
        autoconnect = true;
      };
      gsm = {
        apn = "h2g2";
        # MTU 1200: outgoing path MTU on Google Fi is ~1228 bytes (confirmed by
        # DF-bit ping probing) and ICMP Fragmentation Needed is suppressed, so
        # PMTU discovery never fires. Bearer-reported MTU is 1436 but the actual
        # path drops packets silently above ~1228B. With MTU 1200, TCP MSS=1160
        # and max IP packet=1200B, safely under the path limit.
        # gsm.mtu is the correct NM property for cellular interface MTU;
        # ipv4.mtu is ignored for GSM connections (ModemManager owns the bearer).
        mtu = 1200;
      };
      ipv4 = {
        method = "auto";
        route-metric = 1050;
      };
      ipv6 = {
        # Disabled: Linux enforces a 1280-byte minimum MTU on IPv6-enabled
        # interfaces (RFC 2460). With ipv4v6 bearer, this overrides gsm.mtu=1200
        # and pins the interface at 1280, which exceeds the ~1256B path MTU
        # ceiling on Google Fi (confirmed by DF-bit probing). Disabling IPv6
        # removes the floor and lets gsm.mtu=1200 actually take effect.
        method = "disabled";
      };
    };

    # Run RF calibration when wwan0 comes up, via NM dispatcher.
    # This fires after the bearer is fully established (MM in steady state, not
    # mid-reconnect), which avoids the MBIM contention that a plain
    # After=ModemManager.service oneshot suffers during nixos-rebuild switch.
    # Runs on every connect: boot, reconnect, and resume from suspend.
    # FoxFlss is backgrounded so the dispatcher doesn't stall NM.
    networking.networkmanager.dispatcherScripts = [
      {
        source = pkgs.writeShellScript "foxflss-rf-cal-dispatcher" ''
          [ "$1" = "wwan0" ] || exit 0
          [ "$2" = "up" ] || exit 0

          # Run in background — NM waits for dispatcher scripts to finish
          # and we don't want to delay the connection appearing active.
          # --collect: auto-remove the transient unit after it finishes so
          # the next 'up' event can reuse the foxflss-rf-cal unit name.
          ${pkgs.systemd}/bin/systemd-run \
            --no-block \
            --collect \
            --unit=foxflss-rf-cal \
            --description="Foxconn DW5934e FCC unlock and RF calibration" \
            ${foxflssRfCalRun}
        '';
        type = "basic";
      }
    ];

    # FoxFlss hardcodes /opt/foxconn/data/ for RF calibration data. Symlink the
    # packaged .dat files there via systemd-tmpfiles (NixOS doesn't manage /opt).
    systemd.tmpfiles.rules = [
      "d /opt/foxconn 0755 root root - -"
      "d /opt/foxconn/data 0755 root root - -"
      "L+ /opt/foxconn/data/DW5932e_RF.dat - - - - ${foxflss}/share/foxflss/DW5932e_RF.dat"
      "L+ /opt/foxconn/data/DW5934e_RF.dat - - - - ${foxflss}/share/foxflss/DW5934e_RF.dat"
    ];
  };
}
