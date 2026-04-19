# Foxconn DW5932e/DW5934e WWAN modem FCC unlock
#
# These modems have an FCC lock that prevents the software radio from turning on.
# The closed-source FoxFlss binary from foxconn-pc/fii_linux performs the unlock
# handshake via the FOX QMI service (0xE3) over MBIM.
#
# ModemManager's fcc-unlock.d mechanism runs the script automatically during
# modem probing, so no manual intervention is needed after boot.
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

  foxflss = pkgs.stdenv.mkDerivation {
    pname = "foxflss";
    version = "1.0.15";

    src = pkgs.fetchFromGitHub {
      owner = "foxconn-pc";
      repo = "fii_linux";
      rev = "c4a3f92f1a1d11dd08b92f5adb5bc1800a115f28";
      hash = "sha256-z/hIWJOyHSM3xN99cKSIXJwfu6+/q3NbV6SSNO4md7g=";
    };

    nativeBuildInputs = [ pkgs.autoPatchelfHook ];
    buildInputs = [ pkgs.glibc ];

    dontBuild = true;

    installPhase = ''
      runHook preInstall
      install -Dm755 Application/FoxFlss/bin/FoxFlss $out/bin/FoxFlss
      install -Dm644 Application/FoxFlss/data/DW5932e_RF.dat $out/share/foxflss/DW5932e_RF.dat
      install -Dm644 Application/FoxFlss/data/DW5934e_RF.dat $out/share/foxflss/DW5934e_RF.dat
      runHook postInstall
    '';
  };

  # FoxFlss shells out to dmidecode to read the system SKU. ModemManager's
  # service PATH includes libqmi and libmbim (when fccUnlockScripts is set)
  # but not dmidecode, so we must put it on PATH explicitly.
  fccUnlockScript = pkgs.writeShellScript "foxconn-dw593xe-fcc-unlock" ''
    # Foxconn DW5932e/DW5934e FCC unlock for ModemManager fcc-unlock.d
    # Called by MM with: <script> <dbus-path> <port1> [<port2> ...]
    export PATH="${pkgs.dmidecode}/bin:$PATH"

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
    fi
    exit $UNLOCK_RESULT
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

    # FoxFlss needs dmidecode to read the system SKU
    environment.systemPackages = [ pkgs.dmidecode ];

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
      };
      ipv4 = {
        method = "auto";
        route-metric = 1050;
      };
      ipv6 = {
        method = "auto";
        never-default = true;
      };
    };

    # TODO: FoxFlss hardcodes /opt/foxconn/data/{DW5932e,DW5934e}_RF.dat for RF
    # calibration data (used by -f Set_RF_SSKU, not by FCC unlock). Symlink them
    # there if RF calibration is ever needed. NixOS doesn't manage /opt by default
    # so this would need a systemd-tmpfiles rule or activation script.
  };
}
