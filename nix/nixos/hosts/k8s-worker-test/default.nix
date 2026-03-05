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
  users.users.${username}.initialHashedPassword = "";
  services.getty.autologinUser = username;

  users.users.${username} = {
    openssh.authorizedKeys.keys = [
      # Add your SSH public key here after initial provisioning
    ];
    extraGroups = [ "systemd-journal" ];
  };
  boot.kernel.sysctl."kernel.dmesg_restrict" = 0;
}
