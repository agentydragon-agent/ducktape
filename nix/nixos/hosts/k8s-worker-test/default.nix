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

  # Cloud-init: consumes Proxmox-injected user data to write
  # /etc/kubespan/agent.yaml, /etc/kubernetes/pki/ca.crt, bootstrap kubeconfig
  services.cloud-init.enable = true;

  # kubespand and kubelet must wait for cloud-init to write config files
  systemd.services.kubespand.after = [ "cloud-final.service" ];
  systemd.services.kubelet.after = [ "cloud-final.service" ];

  ducktape.k8sWorker = {
    enable = true;
    fabric = "kubespan";
  };

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
