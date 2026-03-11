# Dell Rugged 12 tablet
#
# Manual setup steps:
# - SSH keygen and copy:
#   - GitHub
#   - VPS agentydragon, root
# - Transfer over Ansible Vault password into libwallet
#
# Some setup steps are in Ansible - see ansible/rugged.yaml
#
# TODO: Consider moving some packages from home-manager to system level (zsh, compilers like rustc/go/gcc)
# TODO: SSH authorized_keys - add keys to users.users.agentydragon.openssh.authorizedKeys.keys
# TODO: Improved OSK extension - waiting for GNOME 49 support (currently only 43-44)
# TODO: auto-cpufreq - services.auto-cpufreq for dynamic CPU governor (power saving on battery, performance on AC)
# TODO: zram - consider zramSwap.enable for memory compression (swap file already exists at /swap/swapfile)
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
    ../../modules/system-inspection-sudo.nix
    ../../modules/k8s-worker.nix
    ../../modules/ipu7-camera.nix
    ../../modules/sops.nix
  ];

  # Passwordless sudo for system inspection commands
  ducktape.systemInspectionSudo.enable = true;

  # K8s worker (KubeSpan fabric)
  # Credentials placed manually (physical machine, no cloud-init):
  #   /etc/kubespan/agent.yaml     — kubespand config (cluster.id, cluster.secret)
  #   /etc/kubernetes/pki/ca.crt  — cluster CA cert
  #   /etc/kubernetes/bootstrap-kubelet.conf — bootstrap kubeconfig with token
  # IPU7 webcam (Intel Lunar Lake, OV08X40 sensor)
  ducktape.ipu7Camera.enable = true;

  ducktape.k8sWorker = {
    enable = true;
    nodeLabels = {
      "topology.kubernetes.io/region" = "roaming";
      "node.kubernetes.io/role" = "roaming";
    };
    nodeTaints = [ "node-role.kubernetes.io/roaming=true:NoSchedule" ];
  };

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
    acpi # Battery/thermal/AC adapter status
    libsecret # secret-tool for keyring access (used by ansible vault)
    telegram-desktop
    zoom-us
  ];

  # LocalSend: local file sharing across devices (LAN)
  programs.localsend = {
    enable = true;
    openFirewall = true;
  };

  # Steam
  programs.steam.enable = true;

  # Zsh as default shell
  programs.zsh.enable = true;

  # nix-ld: Run dynamically linked binaries (Bazel downloads Python, Rust toolchains, etc.)
  programs.nix-ld.enable = true;

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
