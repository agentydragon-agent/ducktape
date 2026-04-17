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
  keys = import ../../../ssh-keys.nix;
  sshKeys = with keys; [
    wyrm2
    atlas_rsa
    rugged
    rugged_wyrm
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
    ../../modules/workstation.nix
    ../../modules/bazel
    ../../modules/system-inspection-sudo.nix
    ../../modules/k8s-worker.nix
    ../../modules/gpu-monitor.nix
  ];

  # Passwordless sudo for system inspection commands
  ducktape.systemInspectionSudo.enable = true;

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

  # GPU health monitoring — periodic telemetry + dmesg error watcher.
  # See debug/atlas/gpu_lockup_20260417/README.md for context.
  ducktape.gpuMonitor.enable = true;

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
    pkgs.usbutils # lsusb
  ];

  # Podman
  virtualisation.podman.enable = true;

  # GNOME 49 dropped X11 sessions — Wayland is the only option.
  # NixOS auto-disables Wayland for NVIDIA, but the display is QXL (not NVIDIA).
  services.displayManager.gdm.wayland = true;

  # SPICE audio: increase PipeWire quantum to 2048 to eliminate xruns on the
  # virtual ich9-intel-hda device. Adds ~42ms audio latency (vs ~21ms default),
  # acceptable for media playback. See <debug/atlas/spice_audio/README.md>.
  services.pipewire.extraConfig.pipewire."10-spice-quantum" = {
    "context.properties" = {
      "default.clock.quantum" = 2048;
      "default.clock.min-quantum" = 2048;
    };
  };

  # Separate data disks (Proxmox virtio disks).
  # autoFormat creates ext4 on first boot; autoResize grows to full disk size.
  # virtio0=/dev/vda, virtio1=/dev/vdb, virtio2=/dev/vdc, virtio3=/dev/vdd,
  # virtio4=/dev/vde, virtio5=/dev/vdf
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
  fileSystems."/home/agentydragon/.cache/bazel" = {
    device = "/dev/vde"; # 40G SSD (local-zfs) — Bazel output bases
    fsType = "ext4";
    autoFormat = true;
    autoResize = true;
  };
  fileSystems."/home/agentydragon/.cache/bazel/_bazel_agentydragon/cache/repos" = {
    device = "/dev/vdf"; # 100G HDD (tank-hdd) — Bazel repository cache
    fsType = "ext4";
    autoFormat = true;
    autoResize = true;
  };

  # LVM for OpenEBS LVM LocalPV — thin-provisioned volumes with snapshot support.
  # OpenEBS node agent runs privileged and uses host LVM tools via nsenter.
  boot.kernelModules = [ "dm_thin_pool" ];

  # OpenEBS LVM volume groups — idempotent oneshot services that create PV + VG.
  #   openebs-proxmox-ssd: virtio2 (/dev/vdc) — 500GB NVMe (local-zfs)
  #   openebs-proxmox-hdd: virtio6 (/dev/vdg) — 500GB HDD (tank-hdd)
  systemd.services =
    lib.mapAttrs'
      (
        vg: dev:
        lib.nameValuePair "openebs-${vg}-setup" {
          description = "Initialize LVM VG openebs-proxmox-${vg} on ${dev}";
          wantedBy = [ "multi-user.target" ];
          before = [ "kubelet.service" ];
          after = [ "systemd-udev-settle.service" ];
          path = [ pkgs.lvm2 ];
          serviceConfig = {
            Type = "oneshot";
            RemainAfterExit = true;
          };
          script = ''
            if [ ! -b ${dev} ]; then
              echo "Device ${dev} not present, skipping VG setup"
              exit 0
            fi
            if vgs openebs-proxmox-${vg} >/dev/null 2>&1; then
              echo "VG openebs-proxmox-${vg} already exists, activating"
            else
              pvcreate ${dev}
              vgcreate openebs-proxmox-${vg} ${dev}
            fi
            vgchange -ay openebs-proxmox-${vg}
          '';
        }
      )
      {
        ssd = "/dev/vdc";
        hdd = "/dev/vdg";
      };

  # Intermediate directories for the nested repo cache mount.
  # The SSD disk is mounted at ~/.cache/bazel, then the HDD disk is mounted
  # over the repo cache subdirectory inside it.
  systemd.tmpfiles.rules = [
    "d /home/agentydragon/.cache/bazel 0755 agentydragon users -"
    "d /home/agentydragon/.cache/bazel/_bazel_agentydragon 0755 agentydragon users -"
    "d /home/agentydragon/.cache/bazel/_bazel_agentydragon/cache 0755 agentydragon users -"
    "d /home/agentydragon/.cache/bazel/_bazel_agentydragon/cache/repos 0755 agentydragon users -"
  ];

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
