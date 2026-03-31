# GPD host-specific home-manager configuration
#
# To apply: home-manager switch --flake ~/code/ducktape#gpd --impure
# (--impure needed for nixGL on non-NixOS systems)
{
  config,
  pkgs,
  lib,
  ducktapePackages,
  ...
}:
{
  imports = [
    ../home.nix
  ];

  # GPD-specific configuration (laptop with full GUI)
  home.stateVersion = "24.05";

  home.packages = [ ducktapePackages.tana ];
  # TODO: Re-enable when google-drive-service module is fixed (see home.nix imports)
  # services.google-drive.enable = true;
}
