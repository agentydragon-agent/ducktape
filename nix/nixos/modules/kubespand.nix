# kubespand — NixOS module for the standalone KubeSpan daemon
#
# Manages the kubespand systemd service, WireGuard kernel module, firewall,
# and IPv6 forwarding. Config file (/etc/kubespan/agent.yaml) contains secrets
# and is placed by cloud-init (not in the Nix store).
{
  config,
  pkgs,
  lib,
  ...
}:
let
  cfg = config.ducktape.kubespand;
in
{
  options.ducktape.kubespand = {
    enable = lib.mkEnableOption "kubespand (standalone KubeSpan daemon)";

    package = lib.mkOption {
      type = lib.types.package;
      default = pkgs.callPackage ../packages/kubespand.nix { };
      description = "The kubespand binary package";
    };

    configPath = lib.mkOption {
      type = lib.types.str;
      default = "/etc/kubespan/agent.yaml";
      description = "Path to the YAML config file (contains secrets, placed manually)";
    };

    listenPort = lib.mkOption {
      type = lib.types.port;
      default = 51820;
      description = "WireGuard UDP listen port (must match Talos KubeSpan port)";
    };

    debug = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Enable debug logging";
    };
  };

  config = lib.mkIf cfg.enable {
    # WireGuard kernel module
    boot.kernelModules = [ "wireguard" ];

    # IPv6 forwarding (KubeSpan ULA addresses)
    boot.kernel.sysctl."net.ipv6.conf.all.forwarding" = 1;

    # Firewall: allow WireGuard UDP port
    networking.firewall.allowedUDPPorts = [ cfg.listenPort ];

    # State directory for identity keypair
    systemd.tmpfiles.rules = [ "d /var/lib/kubespan 0700 root root -" ];

    systemd.services.kubespand = {
      description = "kubespand — standalone KubeSpan daemon";
      after = [ "network-online.target" ];
      wants = [ "network-online.target" ];
      wantedBy = [ "multi-user.target" ];

      serviceConfig = {
        Type = "simple";
        ExecStart = lib.concatStringsSep " " (
          [
            "${cfg.package}/bin/kubespand"
            "-config"
            cfg.configPath
          ]
          ++ lib.optional cfg.debug "-debug"
        );

        # Health check: consider started once the kubespan WireGuard interface exists.
        # kubespand creates it shortly after startup.
        ExecStartPost = pkgs.writeShellScript "kubespand-wait-interface" ''
          for i in $(seq 1 30); do
            if ${pkgs.iproute2}/bin/ip link show kubespan >/dev/null 2>&1; then
              exit 0
            fi
            sleep 1
          done
          echo "kubespand: kubespan interface not created within 30s" >&2
          exit 1
        '';

        Restart = "on-failure";
        RestartSec = "5";

        # Graceful shutdown (removes WireGuard interface, nftables rules, deregisters from discovery)
        KillMode = "mixed";
        TimeoutStopSec = 30;

        # State directory
        StateDirectory = "kubespan";
      };
    };
  };
}
