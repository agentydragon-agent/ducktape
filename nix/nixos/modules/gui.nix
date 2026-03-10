# GNOME desktop environment
{
  config,
  pkgs,
  lib,
  username,
  ...
}:
{
  imports = [ ./timekpr.nix ];

  # GNOME Desktop
  services.xserver.enable = true;
  services.displayManager.gdm.enable = true;
  services.desktopManager.gnome.enable = true;

  # GNOME settings
  services.gnome.gnome-keyring.enable = true;
  programs.dconf.enable = true;

  # Keyring CLI (secret-tool)
  environment.systemPackages = [ pkgs.libsecret ];

  # Screen time management
  ducktape.timekpr = {
    enable = true;
    users.${username} = {
      lockoutType = "lock";
      allowedHours = [
        # 22:00-01:00: allow :00-:50 (forced 10-min break before each hour)
        {
          hours = [ 22 23 0 ];
          minuteRange = "00-50";
        }
        # 01:00-05:00: allow :00-:15 (mostly locked out overnight)
        {
          hours = [ 1 2 3 4 ];
          minuteRange = "00-15";
        }
        # 05:00-22:00: full access
        {
          hours = [ 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 ];
          minuteRange = "00-60";
        }
      ];
    };
  };
}
