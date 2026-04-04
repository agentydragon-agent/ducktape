# Placeholder hardware configuration for iguana
# This will be replaced by nixos-generate-config during installation
#
# To generate the real hardware config during installation:
#   nixos-generate-config --root /mnt
#   cp /mnt/etc/nixos/hardware-configuration.nix \
#      /mnt/home/agentydragon/code/ducktape/nix/nixos/hosts/iguana/
{
  config,
  lib,
  pkgs,
  modulesPath,
  ...
}:
{
  imports = [
    (modulesPath + "/installer/scan/not-detected.nix")
  ];

  # These are placeholder values - will be replaced during installation
  boot.initrd.availableKernelModules = [
    "xhci_pci"
    "thunderbolt"
    "nvme"
    "usbhid"
    "usb_storage"
    "sd_mod"
  ];
  boot.initrd.kernelModules = [ ];
  boot.kernelModules = [ "kvm-intel" ];
  boot.extraModulePackages = [ ];

  # PLACEHOLDER: This will be replaced with actual LUKS device UUID
  # Format will be: /dev/disk/by-uuid/XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX
  boot.initrd.luks.devices."cryptroot".device = "/dev/nvme0n1p5"; # Will be updated with UUID

  # Btrfs subvolumes (created during installation)
  fileSystems."/" = {
    device = "/dev/mapper/cryptroot";
    fsType = "btrfs";
    options = [
      "subvol=@root"
      "compress=zstd"
      "noatime"
    ];
  };

  fileSystems."/home" = {
    device = "/dev/mapper/cryptroot";
    fsType = "btrfs";
    options = [
      "subvol=@home"
      "compress=zstd"
      "noatime"
    ];
  };

  fileSystems."/nix" = {
    device = "/dev/mapper/cryptroot";
    fsType = "btrfs";
    options = [
      "subvol=@nix"
      "compress=zstd"
      "noatime"
    ];
  };

  fileSystems."/swap" = {
    device = "/dev/mapper/cryptroot";
    fsType = "btrfs";
    options = [
      "subvol=@swap"
      "noatime"
    ];
  };

  fileSystems."/var/lib/containerd" = {
    device = "/dev/mapper/cryptroot";
    fsType = "btrfs";
    options = [
      "subvol=@containerd"
      "noatime"
    ];
  };

  fileSystems."/var/local-path-provisioner" = {
    device = "/dev/mapper/cryptroot";
    fsType = "btrfs";
    options = [
      "subvol=@local-path-provisioner"
      "noatime"
    ];
  };

  # PLACEHOLDER: Boot partition UUID will be updated during installation
  fileSystems."/boot" = {
    device = "/dev/nvme0n1p1"; # Will be updated with UUID
    fsType = "vfat";
    options = [
      "fmask=0022"
      "dmask=0022"
    ];
  };

  swapDevices = [
    {
      device = "/swap/swapfile";
      size = 32 * 1024; # 32GB - adjust based on RAM size
    }
  ];

  nixpkgs.hostPlatform = lib.mkDefault "x86_64-linux";
  hardware.cpu.intel.updateMicrocode = lib.mkDefault config.hardware.enableRedistributableFirmware;
}
