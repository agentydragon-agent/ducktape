# iguana (ThinkPad X1 Extreme) host-specific home-manager configuration
#
# Migrated from: nix/home/hosts/agentydragon.nix (Pop!_OS)
#
# Changes from Pop!_OS setup:
# - Removed modules/popos-bazel.nix (not needed on NixOS)
# - No longer need nixGL (native drivers on NixOS)
# - No longer need --impure flag for home-manager switch
#
# To apply: home-manager switch --flake ~/code/ducktape#iguana
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

  home.stateVersion = "24.11";

  # Machine-specific overrides can go here if needed
  # For now, we inherit all settings from home.nix with the feature flags
  # set in flake.nix (enableGui, enableKube, etc.)
}
