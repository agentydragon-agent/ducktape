# k8s-worker-test — NixOS VM for testing K8s worker node enrollment
#
# This is a test VM that runs GNOME desktop + Kubernetes worker.
# See nix/nixos/modules/k8s-worker.nix for manual setup steps.
{
  config,
  pkgs,
  lib,
  username,
  ...
}:
{
  imports = [
    ../../modules/gui.nix
    ../../modules/vm-unattended.nix
    ../../modules/dev-workstation.nix
    ../../modules/hm-bootstrap.nix
    ../../modules/k8s-worker.nix
  ];

  time.timeZone = "UTC";

  ducktape.k8sWorker = {
    enable = true;
    # Replace with actual IPs after cluster bootstrap.
    # VPS IPs: hcloud server list -o columns=name,ipv4
    # Proxmox CP: 10.2.1.1 (reachable via Tailscale subnet route from atlas)
    # HAProxy health checks handle unreachable backends (e.g., Proxmox
    # before Tailscale connects) — falls over to VPS nodes.
    controlPlaneEndpoints = [
      "5.78.106.249:6443" # talos-vps-cp-0
      "5.78.43.147:6443" # talos-vps-cp-1
      "10.2.1.1:6443" # talos-pve-cp-0 (via Tailscale)
    ];
  };

  users.users.${username} = {
    openssh.authorizedKeys.keys = [
      # Add your SSH public key here after initial provisioning
    ];
    extraGroups = [ "systemd-journal" ];
  };
  boot.kernel.sysctl."kernel.dmesg_restrict" = 0;
}
