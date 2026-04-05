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
    ../../modules/sops.nix
    ../../modules/k8s-worker.nix
    ../../modules/k8s-worker-sops.nix
  ];

  # Passwordless sudo for system inspection commands
  ducktape.systemInspectionSudo.enable = true;

  # TODO: Generate attic token for iguana and create secrets/iguana-attic.yaml
  # sops.secrets.attic_token.sopsFile = ../../../../secrets/iguana-attic.yaml;

  # Nebula mesh + k8s worker credentials (wired via k8s-worker-sops module)
  ducktape.k8sWorkerSops = {
    hostname = "iguana";
    nebulaFile = ../../../../secrets/iguana-nebula.yaml;
  };
  ducktape.k8sWorker = {
    enable = true;
    nodeLabels = {
      "topology.kubernetes.io/region" = "home";
      "node.kubernetes.io/role" = "worker";
    };
  };

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
      "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFfzLZ7zOOMviYrrxeh1nSXdwu9uveSXr07EJI5NwFau agentydragon@wyrm"
      "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQCjjx4KmqlVN1JXcjLO9ZxTCQMkXJ2pD4nj90PrTEURFG71YxW+M88jyGNwfCl1eMVPC9eU7b8yA+tZv90cWlRc9Hxi2FPNLqyv+6HUqCz88C/KoFW3AkBcI0cIDJsa83x04CKil3imIMk70JfPU7Rio7Jlo4RoZ/oo8zovRDBkhR1TLHH8FEo+rXZNEEoNM/S90MGmPpAhK5W3ggKO2lq1hhU6fCNjaG+PGpL/VRAq+icLakYOYahsUEBHKcqHmEiFPPW4Ic6U+I+83ec0EgF0kmOZveU6RPH6G23femFbd8T4gJcl8biLhCblV9VDRnmPuKeygMVUKf9wxlE4KdImVrgfVMppBoA0Z3f93utl/9LDgugwAjAyDS0XxP0lyTl62DQ/bamUM8kK00iZcYIH1v1gjrX8yXFeTbwcd81s5hWY3VCJ6rUhJsXeT0cNxEIv0E1BFXq68aTtJ5CVyWksdNafuBEzvKBVyrmF3Gv5uAnPaXfSd4NwyaQplq1ZZaM= agentydragon@atlas"
    ];
  };

  # Allow reading kernel logs without sudo
  boot.kernel.sysctl."kernel.dmesg_restrict" = 0;

  # ThinkPad-specific optimizations
  # TrackPoint configuration (if desired)
  # services.xserver.libinput.enable = true;
  # services.xserver.libinput.touchpad.tapping = false; # Disable tap-to-click if preferred
}
