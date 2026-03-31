# Standalone flake for KVM stall test VM images.
# Builds minimal NixOS qcow2 images with controllable kernel versions.
#
# Usage:
#   nix build .#kvm-test-6_12-image
#   scp result/disk.qcow2 root@atlas:/tmp/kvm-test-6_12.qcow2
{
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.11";

  outputs =
    { nixpkgs, ... }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};

      sshKey = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFfzLZ7zOOMviYrrxeh1nSXdwu9uveSXr07EJI5NwFau agentydragon@popvm";

      # Base NixOS module for all test VMs
      baseModule =
        { lib, pkgs, ... }:
        {
          system.stateVersion = "25.11";

          # Boot
          boot.loader.systemd-boot.enable = true;
          boot.loader.efi.canTouchEfiVariables = true;
          boot.consoleLogLevel = 7;
          boot.kernelParams = lib.mkDefault [
            "console=ttyS0,115200"
            "console=tty0"
          ];

          # Serial console for qm terminal access
          systemd.services."serial-getty@ttyS0".enable = true;
          boot.initrd.availableKernelModules = [
            "ahci"
            "xhci_pci"
            "virtio_pci"
            "sr_mod"
            "virtio_blk"
          ];

          # QEMU guest
          services.qemuGuest.enable = true;
          # Skip spice-vdagentd — pulls in GTK/libcanberra which has build issues

          # Root filesystem
          fileSystems."/" = lib.mkDefault {
            device = "/dev/disk/by-label/nixos";
            fsType = "ext4";
          };
          fileSystems."/boot" = lib.mkDefault {
            device = "/dev/disk/by-label/ESP";
            fsType = "vfat";
          };

          # SSH
          services.openssh = {
            enable = true;
            settings = {
              PasswordAuthentication = false;
              PermitRootLogin = "yes";
            };
          };

          # Users — both root and test user get SSH access
          users.users.root.openssh.authorizedKeys.keys = [ sshKey ];
          users.users.test = {
            isNormalUser = true;
            extraGroups = [ "wheel" ];
            openssh.authorizedKeys.keys = [ sshKey ];
          };
          security.sudo.wheelNeedsPassword = false;

          # Test tools
          environment.systemPackages = [ pkgs.stress-ng ];

          # Size reduction — strip everything not needed for diagnosis
          nix.enable = false;
          documentation.enable = false;
          programs.command-not-found.enable = false;
          services.udev.hwdb.enable = false;
          systemd.coredump.enable = false;
          systemd.oomd.enable = false;
          fonts.fontconfig.enable = false;
          boot.supportedFilesystems = lib.mkForce [
            "ext4"
            "vfat"
          ];
          boot.initrd.includeDefaultModules = false;

          # Console auto-login for screenshot debugging
          services.getty.autologinUser = "test";

          # Use simple interface names (eth0) instead of predictable names
          networking.usePredictableInterfaceNames = false;

          # Networking defaults (overridden per variant)
          networking.useDHCP = lib.mkDefault false;
          networking.interfaces.eth0.ipv4.addresses = lib.mkDefault [
            {
              address = "10.0.200.1";
              prefixLength = 16;
            }
          ];
          networking.defaultGateway = lib.mkDefault "10.0.0.1";
          networking.nameservers = lib.mkDefault [
            "1.1.1.1"
            "8.8.8.8"
          ];
        };

      # Helper to create a test VM NixOS configuration
      mkTestVm =
        {
          ip,
          kernelPackages,
          hostname ? "kvm-test",
          extraKernelParams ? [ ],
        }:
        nixpkgs.lib.nixosSystem {
          inherit system;
          modules = [
            baseModule
            {
              networking.hostName = hostname;
              boot.kernelPackages = kernelPackages;
              boot.kernelParams = extraKernelParams;
              networking.interfaces.eth0.ipv4.addresses = [
                {
                  address = ip;
                  prefixLength = 16;
                }
              ];
            }
          ];
        };

      # Test VM variants
      variants = {
        "kvm-test-6_12" = mkTestVm {
          ip = "10.0.200.1";
          kernelPackages = pkgs.linuxPackages_6_12;
        };
        "kvm-test-6_18" = mkTestVm {
          ip = "10.0.200.3";
          kernelPackages = pkgs.linuxPackages_6_18;
        };
        "kvm-test-6_19" = mkTestVm {
          ip = "10.0.200.4";
          kernelPackages = pkgs.linuxPackages_6_19;
        };
        "kvm-test-6_18-tsa-off" = mkTestVm {
          ip = "10.0.200.7";
          kernelPackages = pkgs.linuxPackages_6_18;
          extraKernelParams = [ "tsa=off" ];
        };
        "kvm-test-6_18-mitigations-off" = mkTestVm {
          ip = "10.0.200.8";
          kernelPackages = pkgs.linuxPackages_6_18;
          extraKernelParams = [ "mitigations=off" ];
        };
      };
    in
    {
      nixosConfigurations = variants;

      packages.${system} = builtins.mapAttrs (
        name: config: config.config.system.build.images.qemu-efi
      ) variants;
    };
}
