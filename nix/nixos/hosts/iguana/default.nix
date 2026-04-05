# ThinkPad X1 Extreme workstation
#
# Hardware:
# - CPU: Intel Core (CometLake-H)
# - GPU: Intel UHD Graphics (integrated) + NVIDIA GTX 1650 Ti Mobile (discrete, Optimus)
# - Storage: 954GB NVMe SSD (btrfs on LUKS, no LVM currently)
#   If OpenEBS LVM provisioner is needed later: shrink btrfs, shrink LUKS,
#   repartition to carve out an LVM PV, or re-do as LUKS → LVM → btrfs.
#
# Manual setup steps:
# - SSH keygen and copy to GitHub/GitLab
# - Transfer Ansible Vault password into libwallet
# - sops-nix age key generation (for when secrets are needed)
# - Nebula certs (will be added out-of-band later, via Google Keep or similar)
#
# Migration notes:
# - Migrated from Pop!_OS (ext4) to NixOS (btrfs) in-place
# - Previously managed via Ansible + home-manager (nix/home/hosts/agentydragon.nix)
# - CUDA support for NVIDIA discrete GPU
{
  config,
  pkgs,
  lib,
  username,
  ...
}:
{
  imports = [
    ./hardware-configuration.nix
    ../../modules/gui.nix
    ../../modules/dev-workstation.nix
    ../../modules/bazel-dev.nix
    ../../modules/system-inspection-sudo.nix
    # ../../modules/sops.nix  # TODO: Enable after first boot (needs host SSH key for age decryption)
    # ../../modules/k8s-worker.nix  # TODO: Uncomment when ready to join cluster
  ];

  # Passwordless sudo for system inspection commands
  ducktape.systemInspectionSudo.enable = true;

  # Attic cache push token
  # TODO: Uncomment after first boot and sops-nix setup (need host SSH key first)
  # sops.secrets.attic_token.sopsFile = ../../../../secrets/iguana-attic.yaml;

  # TODO: Uncomment when ready to join k8s cluster
  # Nebula certs and k8s worker credentials will be added out-of-band first
  # sops.secrets.nebula_ca_cert.sopsFile = ../../../../secrets/k8s-worker.yaml;
  # sops.secrets.k8s_ca_cert.sopsFile = ../../../../secrets/k8s-worker.yaml;
  # sops.secrets.k8s_bootstrap_token.sopsFile = ../../../../secrets/k8s-worker.yaml;
  # sops.secrets.nebula_host_cert.sopsFile = ../../../../secrets/iguana-nebula.yaml;
  # sops.secrets.nebula_host_key.sopsFile = ../../../../secrets/iguana-nebula.yaml;
  #
  # ducktape.nebulaMesh.caCertPath = config.sops.secrets.nebula_ca_cert.path;
  # ducktape.nebulaMesh.hostCertPath = config.sops.secrets.nebula_host_cert.path;
  # ducktape.nebulaMesh.hostKeyPath = config.sops.secrets.nebula_host_key.path;
  #
  # ducktape.k8sWorker = {
  #   enable = true;
  #   caCertPath = config.sops.secrets.k8s_ca_cert.path;
  #   bootstrapTokenPath = config.sops.secrets.k8s_bootstrap_token.path;
  #   nodeLabels = {
  #     "topology.kubernetes.io/region" = "home";
  #     "node.kubernetes.io/role" = "worker";
  #   };
  # };

  # Timezone
  time.timeZone = "America/Los_Angeles";

  # Bluetooth
  hardware.bluetooth = {
    enable = true;
    powerOnBoot = true;
  };

  # NVIDIA GPU configuration (GTX 1650 Ti Mobile, Optimus setup)
  hardware.nvidia = {
    modesetting.enable = true;
    powerManagement.enable = true; # Battery-friendly on laptop
    powerManagement.finegrained = false; # Disable finegrained for Optimus (use PRIME)
    open = false; # Proprietary driver for GTX 1650 Ti (open doesn't support it yet)
    nvidiaSettings = true; # GUI settings app
    package = config.boot.kernelPackages.nvidiaPackages.stable;

    # Optimus configuration - use NVIDIA on-demand
    prime = {
      offload = {
        enable = true;
        enableOffloadCmd = true; # Provides nvidia-offload command
      };
      # Bus IDs from lspci output:
      # 00:02.0 = Intel UHD Graphics
      # 01:00.0 = NVIDIA GTX 1650 Ti
      intelBusId = "PCI:0:2:0";
      nvidiaBusId = "PCI:1:0:0";
    };
  };
  services.xserver.videoDrivers = [ "nvidia" ];

  # CUDA support
  # Applications needing CUDA should use nvidia-offload:
  #   nvidia-offload <command>
  # Or set environment variable:
  #   __NV_PRIME_RENDER_OFFLOAD=1 __GLX_VENDOR_LIBRARY_NAME=nvidia <command>
  hardware.graphics = {
    enable = true;
    enable32Bit = true; # For 32-bit apps/games
  };

  # Services
  services = {
    avahi = {
      enable = true;
      nssmdns4 = true; # mDNS resolution for .local hostnames
    };
    blueman.enable = true;
    fwupd.enable = true; # Firmware updates
    printing.enable = true;
    openssh.enable = true;

    thermald.enable = true;

    # Lid/power button behavior
    logind.settings.Login = {
      HandleLidSwitch = "suspend";
      HandleLidSwitchExternalPower = "lock";
      HandlePowerKey = "suspend";
      HandlePowerKeyLongPress = "poweroff";
    };
  };

  # System packages
  environment.systemPackages = with pkgs; [
    acpi
    powertop # Power consumption analysis
    pciutils # lspci
    usbutils # lsusb
    strace
    bandwhich
    nethogs
    telegram-desktop
    vlc
    zoom-us
    gimp
    # nvidia-offload wrapper is provided by hardware.nvidia.prime.offload.enableOffloadCmd
  ];

  # Local file sharing across devices (LAN)
  programs.localsend = {
    enable = true;
    openFirewall = true;
  };

  # Zsh as default shell
  programs.zsh.enable = true;

  # User configuration
  users.users.${username} = {
    shell = pkgs.zsh;
    extraGroups = [ "systemd-journal" ];
    openssh.authorizedKeys.keys = [
      "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFfzLZ7zOOMviYrrxeh1nSXdwu9uveSXr07EJI5NwFau agentydragon@popvm"
      # TODO: Add more SSH keys as needed
    ];
  };

  # Allow reading kernel logs without sudo
  boot.kernel.sysctl."kernel.dmesg_restrict" = 0;

  # ThinkPad-specific optimizations
  # TrackPoint configuration (if desired)
  # services.xserver.libinput.enable = true;
  # services.xserver.libinput.touchpad.tapping = false; # Disable tap-to-click if preferred
}
