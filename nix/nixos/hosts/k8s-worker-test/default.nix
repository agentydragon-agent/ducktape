# k8s-worker-test — lean NixOS VM for testing K8s worker node enrollment
#
# Headless (SSH + console only) for fast provisioning.
# Uses Nebula mesh for inter-node connectivity.
#
# TODO: Set up sops-nix for this VM (add age key to .sops.yaml, create
# k8s-worker-test-nebula.yaml) to provide Nebula + K8s credentials.
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
    ../../modules/sops.nix
  ];

  time.timeZone = "UTC";

  # TODO: Add sops secrets and configure cert paths once age key is known,
  # then re-enable k8sWorker.
  # ducktape.k8sWorker.enable = true;

  # Headless auto-login on console
  services.getty.autologinUser = username;

  users.users.${username} = {
    initialHashedPassword = "";
    openssh.authorizedKeys.keys = [
      "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFfzLZ7zOOMviYrrxeh1nSXdwu9uveSXr07EJI5NwFau agentydragon@popvm"
    ];
    extraGroups = [ "systemd-journal" ];
  };
  # Passwordless sudo for test VM (overrides base.nix default)
  security.sudo.wheelNeedsPassword = lib.mkForce false;

  boot.kernel.sysctl."kernel.dmesg_restrict" = 0;
}
