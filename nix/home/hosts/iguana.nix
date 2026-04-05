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
    ../modules/github-ssh.nix
  ];

  ducktape.githubSsh.sopsFile = ../../../secrets/user-iguana-github-ssh.yaml;

  home.stateVersion = "24.11";
}
