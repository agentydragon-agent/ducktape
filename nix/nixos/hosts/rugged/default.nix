# Dell Rugged 12 tablet
#
# Manual setup steps:
# - SSH keygen and copy:
#   - GitHub
#   - VPS agentydragon, root
# - Transfer over Ansible Vault password into libwallet
#
# TODO: Consider moving some packages from home-manager to system level (zsh, compilers like rustc/go/gcc)
# TODO: SSH authorized_keys - add keys to users.users.agentydragon.openssh.authorizedKeys.keys
# TODO: Improved OSK extension - waiting for GNOME 49 support (currently only 43-44)
# TODO: auto-cpufreq - services.auto-cpufreq for dynamic CPU governor (power saving on battery, performance on AC)
# TODO: zram - consider zramSwap.enable for memory compression (swap file already exists at /swap/swapfile)
# TODO: Vulkan crash on Lunar Lake - Snapshot (and likely other GTK4 apps) segfault with VK_ERROR_DEVICE_LOST.
#   Workaround: GSK_RENDERER=gl. Consider adding to environment.sessionVariables or wrapping affected apps.
# TODO: IPU7 camera not visible to Zoom and browsers. Likely need PipeWire camera portal / xdg-desktop-portal
#   integration so non-libcamera apps can access the camera. Snapshot with GSK_RENDERER=gl works.
# TODO: PipeWire - explicit audio config (services.pipewire with pulse/alsa/jack support)
# TODO: bluetooth group - add to extraGroups if direct bluetooth access needed beyond blueman
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
    ../../modules/k8s-worker.nix
    ../../modules/ipu7-camera.nix
    ../../modules/sops.nix
  ];

  # Passwordless sudo for system inspection commands
  ducktape.systemInspectionSudo.enable = true;

  # Attic cache push token
  sops.secrets.attic_token.sopsFile = ../../../../secrets/rugged-attic.yaml;

  # K8s worker (Nebula mesh) — credentials via sops-nix
  sops.secrets.nebula_ca_cert.sopsFile = ../../../../secrets/k8s-worker.yaml;
  sops.secrets.k8s_ca_cert.sopsFile = ../../../../secrets/k8s-worker.yaml;
  sops.secrets.k8s_bootstrap_token.sopsFile = ../../../../secrets/k8s-worker.yaml;
  sops.secrets.nebula_host_cert.sopsFile = ../../../../secrets/rugged-nebula.yaml;
  sops.secrets.nebula_host_key.sopsFile = ../../../../secrets/rugged-nebula.yaml;

  ducktape.nebulaMesh.caCertPath = config.sops.secrets.nebula_ca_cert.path;
  ducktape.nebulaMesh.hostCertPath = config.sops.secrets.nebula_host_cert.path;
  ducktape.nebulaMesh.hostKeyPath = config.sops.secrets.nebula_host_key.path;

  ducktape.k8sWorker = {
    enable = true;
    caCertPath = config.sops.secrets.k8s_ca_cert.path;
    bootstrapTokenPath = config.sops.secrets.k8s_bootstrap_token.path;
    nodeLabels = {
      "topology.kubernetes.io/region" = "roaming";
      "node.kubernetes.io/role" = "roaming";
    };
    nodeTaints = [ "node-role.kubernetes.io/roaming=true:NoSchedule" ];
  };

  # IPU7 webcam (Intel Lunar Lake, OV08X40 sensor)
  ducktape.ipu7Camera.enable = true;

  # Separate btrfs subvolumes for containerd and local-path-provisioner storage.
  # Create them before first boot with:
  #   sudo mount -t btrfs /dev/mapper/cryptroot /mnt/btrfs-root
  #   sudo btrfs subvolume create /mnt/btrfs-root/@containerd
  #   sudo btrfs subvolume create /mnt/btrfs-root/@local-path-provisioner
  #   sudo umount /mnt/btrfs-root
  fileSystems."/var/lib/containerd" = {
    device = "/dev/mapper/cryptroot";
    fsType = "btrfs";
    options = [ "subvol=@containerd" ];
  };
  fileSystems."/var/local-path-provisioner" = {
    device = "/dev/mapper/cryptroot";
    fsType = "btrfs";
    options = [ "subvol=@local-path-provisioner" ];
  };

  # Timezone
  time.timeZone = "America/Los_Angeles";

  # Bluetooth
  hardware.bluetooth = {
    enable = true;
    powerOnBoot = true;
  };
  # IIO sensor proxy for accelerometer (auto screen rotation)
  hardware.sensor.iio.enable = true;

  # Services (tailscale enabled via dev-workstation.nix)
  services = {
    avahi = {
      enable = true;
      nssmdns4 = true; # mDNS resolution for .local hostnames (printers, etc.)
    };
    blueman.enable = true;
    fwupd.enable = true; # Firmware updates
    printing.enable = true;
    openssh.enable = true;
    thermald.enable = true; # Intel thermal management
    upower.enable = true; # Battery status (dual battery support)
    logind.settings.Login = {
      HandleLidSwitch = "suspend";
      HandleLidSwitchExternalPower = "lock";
      HandlePowerKey = "suspend";
      HandlePowerKeyLongPress = "poweroff";
    };
  };

  # WWAN/5G modem support (Foxconn DP25-42843-47)
  networking.modemmanager.enable = true;
  programs.nm-applet.enable = true;

  hardware.enableAllFirmware = true;

  # System packages
  environment.systemPackages = with pkgs; [
    acpi
    unzip
    zip
    powertop # Power consumption analysis (useful for tablet battery)
    pciutils # lspci
    usbutils # lsusb
    strace # Syscall tracing for debugging
    # TODO: Remove bandwhich, nethogs (already in home-manager), libsecret (already in gui.nix)
    bandwhich # Per-process/connection/host bandwidth monitor
    nethogs
    snapshot # GNOME camera app (uses libcamera/PipeWire natively)
    libsecret # secret-tool for keyring access (used by ansible vault)
    telegram-desktop
    vlc
    xdg-terminal-exec # Used by custom Ctrl+Alt+T keybinding; configure via xdg-terminals.list
    zoom-us
    gimp
  ];

  # Local file sharing across devices (LAN)
  programs.localsend = {
    enable = true;
    openFirewall = true;
  };

  # Steam
  programs.steam.enable = true;

  # Zsh as default shell
  programs.zsh.enable = true;

  # User configuration
  users.users.${username} = {
    shell = pkgs.zsh;
    # Allow reading system logs without sudo (systemd-journal group)
    extraGroups = [ "systemd-journal" ];
    openssh.authorizedKeys.keys = [
      "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFfzLZ7zOOMviYrrxeh1nSXdwu9uveSXr07EJI5NwFau agentydragon@popvm"
    ];
  };

  # Allow reading kernel logs without sudo
  boot.kernel.sysctl."kernel.dmesg_restrict" = 0;

  # User groups provided by base.nix: wheel, networkmanager, video, audio
}
