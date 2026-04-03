# Dell Rugged 12 tablet - home-manager configuration
#
# Note: This is a NixOS system with enableHeavyPackages = true
# Heavy packages (GIMP, Krita, FreeCAD, Inkscape, Audacity) are NOT installed via home-manager.
# Instead, they should be installed via NixOS system configuration:
#   imports = [ /path/to/ducktape/nix/nixos/heavy-packages-module.nix ];
#   programs.heavyPackages.enable = true;
# See ../heavy-packages.nix for the complete list of heavy packages.
{
  config,
  pkgs,
  lib,
  ...
}:
{
  imports = [
    ../home.nix
    ../modules/15leroy-ssh.nix
    ../modules/github-ssh.nix
  ];

  home.packages = [
    pkgs.lightburn
  ];

  # NixOS doesn't have Pop!_OS's built-in ubuntu-appindicators, so install it
  programs.gnome-shell.extensions = [
    { package = pkgs.gnomeExtensions.appindicator; }
  ];

  home.stateVersion = "25.11";
}
