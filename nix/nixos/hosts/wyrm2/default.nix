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
let
  sshKeys = [
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFfzLZ7zOOMviYrrxeh1nSXdwu9uveSXr07EJI5NwFau agentydragon@wyrm"
    "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQCjjx4KmqlVN1JXcjLO9ZxTCQMkXJ2pD4nj90PrTEURFG71YxW+M88jyGNwfCl1eMVPC9eU7b8yA+tZv90cWlRc9Hxi2FPNLqyv+6HUqCz88C/KoFW3AkBcI0cIDJsa83x04CKil3imIMk70JfPU7Rio7Jlo4RoZ/oo8zovRDBkhR1TLHH8FEo+rXZNEEoNM/S90MGmPpAhK5W3ggKO2lq1hhU6fCNjaG+PGpL/VRAq+icLakYOYahsUEBHKcqHmEiFPPW4Ic6U+I+83ec0EgF0kmOZveU6RPH6G23femFbd8T4gJcl8biLhCblV9VDRnmPuKeygMVUKf9wxlE4KdImVrgfVMppBoA0Z3f93utl/9LDgugwAjAyDS0XxP0lyTl62DQ/bamUM8kK00iZcYIH1v1gjrX8yXFeTbwcd81s5hWY3VCJ6rUhJsXeT0cNxEIv0E1BFXq68aTtJ5CVyWksdNafuBEzvKBVyrmF3Gv5uAnPaXfSd4NwyaQplq1ZZaM= agentydragon@atlas"
  ];
in
{
  # CLEANUP(2026-03-31): Remove overlay once nixpkgs containerd >= 2.2.3.
  # Fixes absolute symlink handling in NixOS-based container images (Go 1.24
  # regression). Cherry-pick of containerd/containerd#12732 to release/2.2
  # (PR #13015, merged 2026-03-12). Needed to run attic pod on wyrm2.
  nixpkgs.overlays = [
    (final: prev: {
      containerd = prev.containerd.overrideAttrs (old: {
        version = "2.2.2-pre-20260326";
        src = final.fetchFromGitHub {
          owner = "containerd";
          repo = "containerd";
          rev = "59b2c55f2684c34aba5cde8a5382e93b31850610";
          hash = "sha256-aAXuPHmkC5tFclrBOXD70m1juLPeUc6EC7CscWP3SZA=";
        };
      });
    })
  ];

  imports = [
    ../../modules/gui.nix
    ../../modules/dev-workstation.nix
    ../../modules/bazel-dev.nix
    ../../modules/system-inspection-sudo.nix
    ../../modules/k8s-worker.nix
    ../../modules/k8s-worker-sops.nix
    ../../modules/sops.nix
  ];

  # Passwordless sudo for system inspection commands
  ducktape.systemInspectionSudo.enable = true;

  # Attic cache push token
  sops.secrets.attic_token.sopsFile = ../../../../secrets/hosts/wyrm2-attic.yaml;

  # Nebula mesh + k8s worker credentials (wired via k8s-worker-sops module)
  ducktape.k8sWorkerSops.hostname = "wyrm2";
  ducktape.k8sWorker = {
    enable = true;
    enableNvidiaRuntime = true;
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

  # Ollama with CUDA for local GPU inference (also used by k8s ollama pod, but
  # useful standalone when cluster is down or for ad-hoc tasks).
  # Models stored on Proxmox CSI PVC (200Gi) or ~/downloads/ollama-models/.
  environment.systemPackages = [
    pkgs.ollama-cuda
    pkgs.poppler-utils # pdftoppm, pdftotext — PDF rendering/extraction
    pkgs.tesseract # OCR
    pkgs.lvm2 # LVM tools for OpenEBS LVM LocalPV
    pkgs.freecad
    pkgs.unzip
  ];

  # Podman
  virtualisation.podman.enable = true;

  # GNOME 49 dropped X11 sessions — Wayland is the only option.
  # NixOS auto-disables Wayland for NVIDIA, but the display is QXL (not NVIDIA).
  services.displayManager.gdm.wayland = true;

  # Separate data disks (Proxmox virtio disks).
  # autoFormat creates ext4 on first boot; autoResize grows to full disk size.
  # virtio0=/dev/vda, virtio1=/dev/vdb, virtio2=/dev/vdc, virtio3=/dev/vdd
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
  # virtio2 (/dev/vdc) is OpenEBS LVM — managed as LVM VG below, not a filesystem mount
  fileSystems."/var/lib/containerd" = {
    device = "/dev/vdd";
    fsType = "ext4";
    autoFormat = true;
    autoResize = true;
  };

  # LVM for OpenEBS LVM LocalPV — thin-provisioned volumes with snapshot support.
  # virtio2 (/dev/vdc) is a dedicated 500GB Proxmox disk for the LVM VG.
  # OpenEBS node agent runs privileged and uses host LVM tools via nsenter.
  boot.kernelModules = [ "dm_thin_pool" ];

  # Create LVM PV + VG on the OpenEBS disk (idempotent oneshot)
  systemd.services.openebs-lvm-setup = {
    description = "Initialize LVM VG for OpenEBS on /dev/vdc";
    wantedBy = [ "multi-user.target" ];
    before = [ "kubelet.service" ];
    after = [ "systemd-udev-settle.service" ];
    path = [ pkgs.lvm2 ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
    };
    script = ''
      if vgs openebs-lvmvg >/dev/null 2>&1; then
        echo "VG openebs-lvmvg already exists, skipping"
        exit 0
      fi
      pvcreate /dev/vdc
      vgcreate openebs-lvmvg /dev/vdc
    '';
  };

  # TODO: Create /mnt/tankshare/shared/{pip-cache,uv-cache} via systemd.tmpfiles.rules
  # and configure pip/uv to use them as cache directories

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
    openssh.authorizedKeys.keys = sshKeys;
    extraGroups = [ "systemd-journal" ];
  };

  users.users.root.openssh.authorizedKeys.keys = sshKeys;
  services.openssh.settings.PermitRootLogin = lib.mkForce "prohibit-password";

  boot.kernel.sysctl."kernel.dmesg_restrict" = 0;

  # MOTD
  users.motd = "🐉 Welcome to wyrm2!\n";
}
