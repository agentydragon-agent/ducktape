# iguana (ThinkPad X1 Extreme) host-specific home-manager configuration
#
# Previously Pop!_OS (agentydragon.nix), now NixOS.
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

  ducktape.githubSsh.sopsFile = ../../../secrets/home/iguana/github-ssh.yaml;

  home.stateVersion = "24.11";
}
