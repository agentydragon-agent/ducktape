# Agentydragon host-specific home-manager configuration
#
# To apply: home-manager switch --flake ~/code/ducktape#agentydragon --impure
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
    ../modules/popos-bazel.nix
  ];

  home.stateVersion = "24.05";
}
