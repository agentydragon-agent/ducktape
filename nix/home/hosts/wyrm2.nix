# Wyrm2 - NixOS dev workstation VM (Proxmox) + k8s worker
# Similar to rugged but for VM deployment.
{
  config,
  pkgs,
  lib,
  ...
}:
let
  tana = pkgs.callPackage ../packages/tana.nix { };
in
{
  imports = [
    ../home.nix
    ../modules/nixos-bazel.nix
  ];

  # NixOS doesn't have Pop!_OS's built-in ubuntu-appindicators, so install it
  home.packages = [
    pkgs.gnomeExtensions.appindicator
    tana
  ];
  dconf.settings."org/gnome/shell".enabled-extensions = [
    "appindicatorsupport@rgcjonas.gmail.com"
  ];

  home.stateVersion = "25.11";
}
