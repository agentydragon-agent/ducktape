# GPD host-specific home-manager configuration
#
# To apply: home-manager switch --flake ~/code/ducktape#gpd --impure
# (--impure needed for nixGL on non-NixOS systems)
{
  config,
  pkgs,
  lib,
  ...
}:
{
  imports = [
    ../home.nix
  ];

  home.stateVersion = "24.05";
}
