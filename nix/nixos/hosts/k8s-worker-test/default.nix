# k8s-worker-test — NixOS VM for testing K8s worker node enrollment
#
# This is a test VM that runs GNOME desktop + Kubernetes worker.
# Uses KubeSpan fabric (kubespand) for mesh connectivity.
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
    fabric = "kubespan";
  };

  users.users.${username} = {
    openssh.authorizedKeys.keys = [
      # Add your SSH public key here after initial provisioning
    ];
    extraGroups = [ "systemd-journal" ];
  };
  boot.kernel.sysctl."kernel.dmesg_restrict" = 0;
}
