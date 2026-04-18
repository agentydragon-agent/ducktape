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
    ../modules/kubeconfig.nix
    ../modules/talosconfig.nix
  ];

  ducktape.githubSsh.sopsFile = ../../../ssh_keys/iguana-github.sops.key;

  home.stateVersion = "24.11";
}
