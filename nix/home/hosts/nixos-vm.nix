# NixOS VM host-specific home-manager configuration (simplified)
#
# To apply: home-manager switch --flake ~/code/ducktape#nixos-vm
# (no --impure needed on NixOS)
#
# Note: enableGui=true, enableKube=false, enableHeavyPackages=false set in flake.nix
#
# This is a lightweight NixOS VM with enableHeavyPackages = false
# No heavy packages are installed to keep the VM minimal.
{
  config,
  pkgs,
  lib,
  ...
}:
{
  imports = [
    ../home.nix
    ../modules/no-screensaver.nix
  ];

  home.stateVersion = "24.05";
}
