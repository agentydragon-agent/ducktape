# Dell Rugged 12 tablet - home-manager configuration
{
  config,
  pkgs,
  lib,
  ...
}: {
  imports = [../home.nix];

  home.stateVersion = "25.11";
}
