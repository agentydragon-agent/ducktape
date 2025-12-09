# NixOS VM host-specific home-manager configuration (simplified)
#
# To apply: cd ~/code/ducktape/nix/home && home-manager switch --flake .#nixos-vm
# (no --impure needed on NixOS)
#
# Note: enableGui=true, enableKube=false set in flake.nix
{
  config,
  pkgs,
  lib,
  ...
}: {
  imports = [
    ../home.nix
  ];

  # VM-specific configuration (GUI enabled, no special customizations)
  home.stateVersion = "24.05";

  # Disable screensaver and screen blanking (for VM)
  dconf.settings = {
    "org/gnome/desktop/session" = {idle-delay = lib.hm.gvariant.mkUint32 0;}; # 0 = never
    "org/gnome/desktop/screensaver" = {lock-enabled = false;};
  };
}
