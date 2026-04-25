# Dell Rugged 12 tablet
#
# Manual setup steps:
# - SSH keygen and copy to GitHub
# - Transfer over Ansible Vault password into libwallet
#
# TODO: Consider moving some packages from home-manager to system level (zsh, compilers like rustc/go/gcc)
# TODO: SSH authorized_keys - add keys to openssh.authorizedKeys.keys
# TODO: Improved OSK extension - waiting for GNOME 49 support (currently only 43-44)
# TODO: auto-cpufreq - services.auto-cpufreq for dynamic CPU governor (power saving on battery, performance on AC)
# TODO: zram - consider zramSwap.enable for memory compression (swap file already exists at /swap/swapfile)
# TODO: Vulkan crash on Lunar Lake - Snapshot (and likely other GTK4 apps) segfault with VK_ERROR_DEVICE_LOST.
#   Workaround: GSK_RENDERER=gl. Consider adding to environment.sessionVariables or wrapping affected apps.
# TODO: PipeWire - explicit audio config (services.pipewire with pulse/alsa/jack support)
# TODO: bluetooth group - add to extraGroups if direct bluetooth access needed beyond blueman
{
  config,
  pkgs,
  lib,
  username,
  ...
}:
let
  keys = import ../../../ssh-keys.nix;
in
{
  imports = [
    ./hardware-configuration.nix
    ../../modules/gui.nix
    ../../modules/workstation.nix
    ../../modules/bazel
    ../../modules/github-fetch-token.nix
    ../../modules/system-inspection-sudo.nix
    ../../modules/k8s-worker.nix
    ./ipu7-camera.nix
    ./foxconn-wwan.nix
    ./local_llm_arc.nix
    ./local_llm_npu.nix
  ];

  # Passwordless sudo for system inspection commands
  ducktape.systemInspectionSudo.enable = true;
  ducktape.githubFetchToken = {
    enable = true;
    sopsFile = ../../../../secrets/shared/gaffer-private-fetch-pat.yaml;
  };

  ducktape.k8sWorker = {
    enable = true;
    nodeLabels = {
      "topology.kubernetes.io/region" = "roaming";
      "node.kubernetes.io/role" = "roaming";
    };
    nodeTaints = [ "node-role.kubernetes.io/roaming=true:NoSchedule" ];
  };

  # IPU7 webcam (Intel Lunar Lake, OV08X40 sensor)
  ducktape.ipu7Camera.enable = true;

  # Local LLM inference (Arc GPU + NPU)
  ducktape.localLlm.arc.enable = true;
  ducktape.localLlm.npu.enable = true;

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

  # Bluetooth
  hardware.bluetooth = {
    enable = true;
    powerOnBoot = true;
  };
  # IIO sensor proxy for accelerometer (auto screen rotation)
  hardware.sensor.iio.enable = true;

  services = {
    avahi = {
      enable = true;
      nssmdns4 = true; # mDNS resolution for .local hostnames (printers, etc.)
    };
    blueman.enable = true;
    fwupd.enable = true; # Firmware updates
    printing.enable = true;
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
  ducktape.foxconnWwan.enable = true;
  programs.nm-applet.enable = true;

  # Native Wayland for Chrome and Electron apps. Without this, they run under
  # XWayland and can't use the PipeWire camera portal (or screen sharing portal).
  # TODO: Check if NIXOS_OZONE_WL is actually needed for PipeWire camera, or if
  #   WebRtcPipeWireCamera alone suffices (the portal is D-Bus, not display-tied).
  #   We only tested both together.
  environment.sessionVariables.NIXOS_OZONE_WL = "1";

  # Enable PipeWire camera portal in Chrome. IPU7 raw V4L2 nodes are non-functional
  # (the ISP pipeline requires libcamera), so Chrome must use the PipeWire camera
  # source via xdg-desktop-portal instead of enumerating /dev/video* directly.
  # TODO: Check if WebRtcPipeWireCamera alone is enough, or if NIXOS_OZONE_WL is
  #   also required. We only tested both together.
  nixpkgs.overlays = [
    (_final: prev: {
      google-chrome = prev.google-chrome.override {
        # WebRtcPipeWireCamera: IPU7 camera requires PipeWire portal (can't enumerate /dev/video* directly)
        # disable-quic: Google Fi carrier blocks UDP, causing QUIC handshake timeouts before TCP fallback
        commandLineArgs = "--enable-features=WebRtcPipeWireCamera --disable-quic";
      };
    })
  ];

  hardware.enableAllFirmware = true;

  # System packages
  environment.systemPackages = with pkgs; [
    powertop # Power consumption analysis (useful for tablet battery)
    snapshot # GNOME camera app (uses libcamera/PipeWire natively)
    telegram-desktop
    xdg-terminal-exec # Used by custom Ctrl+Alt+T keybinding; configure via xdg-terminals.list
    zoom-us

    # WWAN / eSIM management
    lpac # eUICC/eSIM profile management (lpac profile list/download/enable)
    libmbim # mbimcli for MBIM modem queries (signal, UICC, registration)
    libqmi # qmicli for QMI-over-MBIM queries (UIM card status)
  ];

  # Local file sharing across devices (LAN)
  programs.localsend = {
    enable = true;
    openFirewall = true;
  };

  programs.steam.enable = true;

  # User configuration
  users.users.${username} = {
    shell = pkgs.zsh;
    # Allow reading system logs without sudo (systemd-journal group)
    extraGroups = [ "systemd-journal" ];
    openssh.authorizedKeys.keys = with keys; [
      iguana
      wyrm2
      atlas
    ];
  };

  # SPICE USB redirection helper (setuid root for USB device passthrough)
  security.wrappers.spice-client-glib-usb-acl-helper = {
    setuid = true;
    owner = "root";
    group = "root";
    source = "${pkgs.spice-gtk}/bin/spice-client-glib-usb-acl-helper";
  };

  # User groups provided by base.nix: wheel, networkmanager, video, audio
}
