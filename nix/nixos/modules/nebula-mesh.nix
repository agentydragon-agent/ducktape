# Nebula mesh network module for NixOS workers
# Provides Nebula mesh overlay for inter-node connectivity.
#
# Set caCertPath/hostCertPath/hostKeyPath (e.g. to sops-nix secret paths) to
# generate /etc/nebula/config.yaml from Nix. Lighthouses/staticHostMap have
# sensible defaults for the allegedly.works cluster.
{
  config,
  pkgs,
  lib,
  ...
}:
let
  cfg = config.ducktape.nebulaMesh;
  generatedConfig = builtins.toJSON {
    pki = {
      ca = cfg.caCertPath;
      cert = cfg.hostCertPath;
      key = cfg.hostKeyPath;
    };
    static_host_map = cfg.staticHostMap;
    lighthouse = {
      am_lighthouse = false;
      interval = 10;
      hosts = cfg.lighthouses;
    };
    relay = {
      relays = cfg.lighthouses;
      use_relays = true;
    };
    listen = {
      host = "0.0.0.0";
      port = 4242;
    };
    punchy = {
      punch = true;
      respond = true;
    };
    tun = {
      dev = "nebula1";
    };
    firewall = {
      outbound = [
        {
          port = "any";
          proto = "any";
          host = "any";
        }
      ];
      inbound = [
        {
          port = "any";
          proto = "any";
          host = "any";
        }
      ];
    };
  };
in
{
  options.ducktape.nebulaMesh = {
    enable = lib.mkEnableOption "Nebula mesh network";

    lighthouses = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [
        "10.42.0.1"
        "10.42.0.2"
      ];
      description = "Nebula IPs of lighthouse nodes";
    };

    staticHostMap = lib.mkOption {
      type = lib.types.attrsOf (lib.types.listOf lib.types.str);
      default = {
        "10.42.0.1" = [ "5.78.106.249:4242" ];
        "10.42.0.2" = [ "5.78.43.147:4242" ];
      };
      description = "Nebula IP → [public_ip:port] mapping for lighthouses";
    };

    caCertPath = lib.mkOption {
      type = lib.types.str;
      description = "Path to Nebula CA cert file (e.g. sops secret path)";
    };

    hostCertPath = lib.mkOption {
      type = lib.types.str;
      description = "Path to host cert file (e.g. sops secret path)";
    };

    hostKeyPath = lib.mkOption {
      type = lib.types.str;
      description = "Path to host key file (e.g. sops secret path)";
    };
  };

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [ pkgs.nebula ];

    environment.etc."nebula/config.yaml".text = generatedConfig;

    # Nebula mesh UDP port
    networking.firewall.allowedUDPPorts = [ 4242 ];

    # Loose reverse path filter — Nebula TUN traffic can trigger rpfilter
    # checks the same way WireGuard traffic does (decrypted packets arrive
    # on nebula1 with source IPs whose reverse path goes via the physical interface).
    networking.firewall.checkReversePath = "loose";

    # systemd-resolved for split DNS — lighthouse DNS resolves bare mesh
    # hostnames (cert names), normal DNS handles everything else.
    # ResolveUnicastSingleLabel: by default, resolved does NOT send
    # single-label names (no dots) to DNS servers — it only tries
    # mDNS/LLMNR. Nebula cert names are single-label ("rugged", "wyrm2"),
    # so we must enable this.
    services.resolved = {
      enable = true;
      extraConfig = "ResolveUnicastSingleLabel=yes";
    };

    # NetworkManager should not touch the Nebula TUN interface.
    networking.networkmanager.unmanaged = [ "nebula1" ];

    # State directory for Nebula
    systemd.tmpfiles.rules = [ "d /var/lib/nebula 0700 root root -" ];

    systemd.services.nebula = {
      description = "Nebula mesh network";
      after = [
        "network-online.target"
        "systemd-resolved.service"
      ];
      wants = [
        "network-online.target"
        "systemd-resolved.service"
      ];
      wantedBy = [ "multi-user.target" ];

      serviceConfig = {
        Type = "simple";
        ExecStart = "${pkgs.nebula}/bin/nebula -config /etc/nebula/config.yaml";
        # Configure nebula1 link DNS after the TUN interface is up.
        # Lighthouse DNS resolves bare cert names (e.g., "rugged" → 10.42.0.30).
        # default-route=true makes nebula1 an additional default DNS route
        # (not exclusive). systemd-resolved queries both nebula1 and the regular
        # interface in parallel — first positive reply wins, so lighthouse
        # NXDOMAIN for regular names doesn't break normal resolution.
        # (Using ~. routing domain instead would make nebula1 the EXCLUSIVE
        # handler, breaking regular DNS when lighthouse returns NXDOMAIN.)
        ExecStartPost = pkgs.writeShellScript "nebula-dns-setup" ''
          for i in $(seq 1 30); do
            if ${pkgs.iproute2}/bin/ip link show nebula1 &>/dev/null; then
              break
            fi
            sleep 1
          done
          ${pkgs.systemd}/bin/resolvectl dns nebula1 ${lib.concatStringsSep " " cfg.lighthouses}
          ${pkgs.systemd}/bin/resolvectl default-route nebula1 true
        '';
        Restart = "on-failure";
        RestartSec = "5";
        # Required capabilities for TUN device management
        AmbientCapabilities = "CAP_NET_ADMIN CAP_NET_RAW";
        CapabilityBoundingSet = "CAP_NET_ADMIN CAP_NET_RAW";
      };
    };
  };
}
