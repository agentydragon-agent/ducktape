# k8s-worker-test — lean NixOS VM for testing K8s worker node enrollment
#
# Headless (SSH + console only) for fast provisioning.
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
    ../../modules/k8s-worker.nix
  ];

  time.timeZone = "UTC";

  ducktape.k8sWorker = {
    enable = true;
    fabric = "kubespan";
  };

  # Headless auto-login on console
  services.getty.autologinUser = username;

  users.users.${username} = {
    initialHashedPassword = "";
    openssh.authorizedKeys.keys = [
      # Add your SSH public key here after initial provisioning
    ];
    extraGroups = [ "systemd-journal" ];
  };
  # Passwordless sudo for test VM (overrides base.nix default)
  security.sudo.wheelNeedsPassword = lib.mkForce false;

  boot.kernel.sysctl."kernel.dmesg_restrict" = 0;
}
