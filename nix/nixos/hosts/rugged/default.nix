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
# TODO: logind - services.logind settings for lid close behavior, power button action (HandleLidSwitch, HandlePowerKey)
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
}: {
  imports = [
    ./hardware-configuration.nix
    ../../modules/gui.nix
    ../../modules/dev-workstation.nix
    ../../modules/system-inspection-sudo.nix
  ];

  # Passwordless sudo for system inspection commands
  ducktape.systemInspectionSudo.enable = true;

  # Timezone
  time.timeZone = "America/Los_Angeles";

  # Bluetooth
  hardware.bluetooth = {
    enable = true;
    powerOnBoot = true;
  };
  services.blueman.enable = true;

  # Firmware updates
  services.fwupd.enable = true;
  hardware.enableAllFirmware = true;

  # Printing
  services.printing.enable = true;

  # SSH
  services.openssh.enable = true;

  # System packages
  environment.systemPackages = with pkgs; [
    libsecret # secret-tool for keyring access (used by ansible vault)
  ];

  # Zsh as default shell
  programs.zsh.enable = true;

  # User configuration
  users.users.${username} = {
    shell = pkgs.zsh;
    # Allow reading system logs without sudo (systemd-journal group)
    extraGroups = ["systemd-journal"];
  };

  # Allow reading kernel logs without sudo
  boot.kernel.sysctl."kernel.dmesg_restrict" = 0;

  # User groups provided by base.nix: wheel, networkmanager, video, audio
}
