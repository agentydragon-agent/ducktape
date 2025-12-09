# GPD host-specific home-manager configuration
#
# To apply: cd ~/code/ducktape/nix/home && home-manager switch --flake .#gpd --impure
# (--impure needed for nixGL on non-NixOS systems)
{
  config,
  pkgs,
  lib,
  ...
}: {
  imports = [
    ../home.nix
  ];

  # GPD-specific configuration (laptop with full GUI)
  home.stateVersion = "24.05";
  services.google-drive.enable = true;
}
