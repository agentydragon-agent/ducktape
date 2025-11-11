# Wyrm host-specific home-manager configuration
{
  config,
  pkgs,
  lib,
  ...
}: {
  imports = [
    (import ../home.nix {
      inherit config pkgs lib;
      enableGui = true;
      enableKube = true;
    })
  ];

  # Wyrm-specific configuration (VM/desktop with full GUI)
  home.stateVersion = "24.05";
  services.google-drive.enable = true;

  # Disable screensaver and screen blanking (for VM/wyrm)
  dconf.settings = {
    "org/gnome/desktop/session" = {idle-delay = lib.hm.gvariant.mkUint32 0;}; # 0 = never
    "org/gnome/desktop/screensaver" = {lock-enabled = false;};
  };

  # Wyrm-specific pip configuration for tankshare storage
  # This creates ~/.config/pip/pip.conf to use shared cache
  # Only applies when /tank/share exists
  xdg.configFile."pip/pip.conf" = lib.mkIf (builtins.pathExists "/tank/share") {
    text = ''
      [global]
      cache-dir = /tank/share/pip-cache

      [install]
      user = true
    '';
  };
}
