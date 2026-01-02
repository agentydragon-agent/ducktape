# Hardware configuration for Proxmox VMs
# This is a generic template - the actual hardware-configuration.nix
# is generated on the VM by nixos-generate-config
{
  config,
  lib,
  pkgs,
  modulesPath,
  ...
}: {
  imports = [
    (modulesPath + "/profiles/qemu-guest.nix")
  ];

  # QEMU guest agent for Proxmox integration
  services.qemuGuest.enable = true;

  # Boot configuration for UEFI VMs
  boot.initrd.availableKernelModules = ["ahci" "xhci_pci" "virtio_pci" "sr_mod" "virtio_blk"];
  boot.initrd.kernelModules = [];
  boot.kernelModules = ["kvm-intel" "kvm-amd"];
  boot.extraModulePackages = [];

  # Filesystem - will be overridden by hardware-configuration.nix on the VM
  # These are placeholders for the flake to evaluate
  fileSystems."/" = lib.mkDefault {
    device = "/dev/disk/by-label/nixos";
    fsType = "ext4";
  };

  fileSystems."/boot" = lib.mkDefault {
    device = "/dev/disk/by-label/boot";
    fsType = "vfat";
  };

  swapDevices = [];

  # Networking - use DHCP
  networking.useDHCP = lib.mkDefault true;

  # Platform
  nixpkgs.hostPlatform = lib.mkDefault "x86_64-linux";
}
