# Wyrm2 - NixOS dev workstation VM + k8s worker
# Similar to rugged (Dell Rugged tablet) but for Proxmox VM.
# Joins the Talos k8s cluster via KubeSpan mesh.
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
    ../../modules/dev-workstation.nix
    ../../modules/system-inspection-sudo.nix
    ../../modules/k8s-worker.nix
  ];

  # Passwordless sudo for system inspection commands
  ducktape.systemInspectionSudo.enable = true;

  # K8s worker (KubeSpan fabric)
  # Cloud-init writes /etc/kubespan/agent.yaml, /etc/kubernetes/pki/ca.crt,
  # and bootstrap kubeconfig. Services must wait for cloud-init.
  services.cloud-init.enable = true;
  systemd.services.kubespand.after = [ "cloud-final.service" ];
  systemd.services.kubelet.after = [ "cloud-final.service" ];
  ducktape.k8sWorker.enable = true;

  time.timeZone = "America/Los_Angeles";

  # Services (tailscale enabled via dev-workstation.nix)
  services = {
    avahi = {
      enable = true;
      nssmdns4 = true;
    };
    printing.enable = true;
  };

  # Zsh as default shell
  programs.zsh.enable = true;

  # nix-ld: Run dynamically linked binaries (Bazel downloads Python, Rust toolchains, etc.)
  programs.nix-ld.enable = true;

  # User configuration
  users.users.${username} = {
    shell = pkgs.zsh;
    openssh.authorizedKeys.keys = [
      "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFfzLZ7zOOMviYrrxeh1nSXdwu9uveSXr07EJI5NwFau agentydragon@wyrm"
    ];
    extraGroups = [ "systemd-journal" ];
  };

  boot.kernel.sysctl."kernel.dmesg_restrict" = 0;
}
