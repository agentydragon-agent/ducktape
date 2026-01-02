# GNOME desktop with auto-login
{
  config,
  pkgs,
  lib,
  username,
  ...
}: {
  # GNOME Desktop
  services.xserver = {
    enable = true;
    displayManager.gdm = {
      enable = true;
      autoSuspend = false;
    };
    desktopManager.gnome.enable = true;
  };

  # Auto-login
  services.displayManager.autoLogin = {
    enable = true;
    user = username;
  };

  # Workaround for auto-login with GNOME
  systemd.services."getty@tty1".enable = false;
  systemd.services."autovt@tty1".enable = false;

  # GNOME settings
  services.gnome.gnome-keyring.enable = true;
  programs.dconf.enable = true;

  # Disable screen lock
  programs.dconf.profiles.user.databases = [
    {
      settings = {
        "org/gnome/desktop/session" = {
          idle-delay = lib.gvariant.mkUint32 0;
        };
        "org/gnome/desktop/screensaver" = {
          lock-enabled = false;
          lock-delay = lib.gvariant.mkUint32 0;
        };
      };
    }
  ];
}
