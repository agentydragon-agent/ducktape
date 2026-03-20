# Wyrm2 - NixOS dev workstation VM + k8s worker
# Similar to rugged (Dell Rugged tablet) but for Proxmox VM.
# Joins the Talos k8s cluster via Nebula mesh.
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
    ../../modules/bazel-dev.nix
    ../../modules/system-inspection-sudo.nix
    ../../modules/k8s-worker.nix
    ../../modules/sops.nix
  ];

  # Passwordless sudo for system inspection commands
  ducktape.systemInspectionSudo.enable = true;

  # K8s worker (Nebula mesh) — credentials via sops-nix
  sops.secrets.nebula_ca_cert.sopsFile = ../../secrets/k8s-worker.yaml;
  sops.secrets.k8s_ca_cert.sopsFile = ../../secrets/k8s-worker.yaml;
  sops.secrets.k8s_bootstrap_kubeconfig.sopsFile = ../../secrets/k8s-worker.yaml;
  sops.secrets.nebula_host_cert.sopsFile = ../../secrets/wyrm2-nebula.yaml;
  sops.secrets.nebula_host_key.sopsFile = ../../secrets/wyrm2-nebula.yaml;

  ducktape.nebulaMesh.caCertPath = config.sops.secrets.nebula_ca_cert.path;
  ducktape.nebulaMesh.hostCertPath = config.sops.secrets.nebula_host_cert.path;
  ducktape.nebulaMesh.hostKeyPath = config.sops.secrets.nebula_host_key.path;

  ducktape.k8sWorker = {
    enable = true;
    enableNvidiaRuntime = true;
    caCertPath = config.sops.secrets.k8s_ca_cert.path;
    bootstrapKubeconfigPath = config.sops.secrets.k8s_bootstrap_kubeconfig.path;
    nodeLabels = {
      "topology.kubernetes.io/region" = "proxmox";
      "topology.kubernetes.io/zone" = "atlas";
      "csi.proxmox.sinextra.dev/max-volume-attachments" = "29";
      "node.longhorn.io/create-default-disk" = "true";
    };
    # nodeTaints = [ "node-role.kubernetes.io/roaming=true:NoSchedule" ];
  };

  # NVIDIA GPU (2x RTX 5090 via VFIO passthrough)
  # Open nvidia module allowlists GPUs by subsystem-ID; Gigabyte RTX 5090 (1458:416f) isn't listed.
  # nvidia-drm modeset=0: Workaround for Blackwell (RTX 5090) VFIO FLR bug — the GPU
  # fails Function Level Reset after VM shutdown, causing host soft lockups. Disabling
  # nvidia-drm modesetting prevents the driver from taking a KMS master reference that
  # complicates FLR teardown. See debug/atlas/black_screen_lockup.md.
  boot.kernelParams = [
    "nvidia.NVreg_OpenRmEnableUnsupportedGpus=1"
    "nvidia-drm.modeset=0"
  ];
  services.xserver.videoDrivers = [ "nvidia" ];
  hardware.nvidia = {
    modesetting.enable = true;
    open = true; # Required for Blackwell (RTX 5090) — proprietary module refuses these GPUs
    nvidiaSettings = false; # No X settings app for headless GPU compute
  };
  hardware.nvidia-container-toolkit.enable = true;

  # GNOME 49 dropped X11 sessions — Wayland is the only option.
  # NixOS auto-disables Wayland for NVIDIA, but the display is QXL (not NVIDIA).
  services.displayManager.gdm.wayland = true;

  # Separate data disks (Proxmox virtual disks).
  # scsi30 avoids collision with Proxmox CSI PVCs (scsi1-29).
  # virtio0 uses a different controller, no SCSI slot conflict.
  # by-id paths are stable across reboots.
  # autoFormat creates ext4 on first boot; autoResize grows to full disk size.
  fileSystems."/var/lib/containerd" = {
    device = "/dev/disk/by-id/scsi-0QEMU_QEMU_HARDDISK_drive-scsi30";
    fsType = "ext4";
    autoFormat = true;
    autoResize = true;
  };
  fileSystems."/var/local-path-provisioner" = {
    device = "/dev/vda";
    fsType = "ext4";
    autoFormat = true;
    autoResize = true;
  };
  fileSystems."/var/mnt/longhorn" = {
    device = "/dev/vdb";
    fsType = "ext4";
    autoFormat = true;
    autoResize = true;
  };

  # virtiofs shared from Proxmox host (atlas)
  fileSystems."/mnt/tankshare" = {
    device = "tankshare";
    fsType = "virtiofs";
    options = [
      "defaults"
      "_netdev"
      "nofail"
    ];
  };

  fileSystems."/code" = {
    device = "code";
    fsType = "virtiofs";
    options = [
      "defaults"
      "_netdev"
      "nofail"
    ];
  };

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

  # User configuration
  users.users.${username} = {
    shell = pkgs.zsh;
    openssh.authorizedKeys.keys = [
      "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFfzLZ7zOOMviYrrxeh1nSXdwu9uveSXr07EJI5NwFau agentydragon@wyrm"
    ];
    extraGroups = [ "systemd-journal" ];
  };

  users.users.root.openssh.authorizedKeys.keys = [
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFfzLZ7zOOMviYrrxeh1nSXdwu9uveSXr07EJI5NwFau agentydragon@wyrm"
  ];
  services.openssh.settings.PermitRootLogin = lib.mkForce "prohibit-password";

  boot.kernel.sysctl."kernel.dmesg_restrict" = 0;
}
