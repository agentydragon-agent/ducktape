# NixOS VM host-specific home-manager configuration (simplified)
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
      enableKube = false;
    })
  ];

  # VM-specific configuration (GUI enabled, no special customizations)
  home.stateVersion = "24.05";

  # Disable screensaver and screen blanking (for VM)
  dconf.settings = {
    "org/gnome/desktop/session" = {idle-delay = lib.hm.gvariant.mkUint32 0;}; # 0 = never
    "org/gnome/desktop/screensaver" = {lock-enabled = false;};
  };
}
