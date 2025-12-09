# Agentydragon host-specific home-manager configuration
#
# To apply: cd ~/code/ducktape/nix/home && home-manager switch --flake .#agentydragon --impure
# (--impure needed for nixGL on non-NixOS systems)
{
  config,
  pkgs,
  lib,
  ...
}: {
  imports = [
    ../home.nix
    ../modules/cosmic.nix
  ];

  # Agentydragon-specific configuration (desktop with full GUI)
  home.stateVersion = "24.05";
  services.google-drive.enable = true;
}
